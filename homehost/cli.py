"""HomeHost CLI — the command-line interface for HomeHost."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    name="homehost",
    help="Turn your laptop into a web server. Host websites from home with zero config.",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=False,
)

console = Console()
err_console = Console(stderr=True)

# ── Error handling ─────────────────────────────────────────────────────────────

def _log_dir() -> Path:
    log_dir = Path.home() / ".homehost" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _configure_file_logger() -> logging.Logger:
    logger = logging.getLogger("homehost.cli")
    if logger.handlers:
        return logger
    handler = logging.FileHandler(_log_dir() / "homehost.log", encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    return logger


def handle_error(error: Exception, code: str = "HH-000") -> None:
    """Display a user-friendly error, log full details, and exit non-zero."""
    logger = _configure_file_logger()
    logger.error(
        "Unhandled error [%s]: %s\n%s",
        code,
        error,
        traceback.format_exc(),
    )
    err_console.print(
        Panel(
            f"[bold red]{code}[/bold red]  {error}\n\n"
            f"[dim]Full details logged to {_log_dir() / 'homehost.log'}[/dim]",
            title="[red]HomeHost Error[/red]",
            border_style="red",
        )
    )
    raise typer.Exit(1)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_process_manager():
    """Return a ProcessManager rooted at ~/.homehost/run."""
    from homehost.core.process import ProcessManager
    run_dir = Path.home() / ".homehost" / "run"
    return ProcessManager(run_dir)


def _resolve_project_name(project: Optional[str]) -> str:
    """Return project name: explicit arg > current directory name."""
    if project:
        return project
    return Path.cwd().name


def _project_exists(name: str) -> bool:
    from homehost.core.config import list_projects
    return name in list_projects()


def _uptime_str(start_time: float) -> str:
    """Convert a start timestamp to a human-readable uptime string."""
    seconds = int(time.time() - start_time)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def _pick_free_port(preferred: int = 8080) -> int:
    from homehost.core.detector import find_available_port, is_port_in_use
    if not is_port_in_use(preferred):
        return preferred
    port = find_available_port(8080, 8099)
    return port if port is not None else preferred


def _build_url(cfg) -> str:
    """Build local URL string from project config."""
    host = "localhost"
    return f"http://{host}:{cfg.server.port}"


def _print_qr(url: str) -> None:
    """Print a simple QR code hint (requires qrcode or just prints URL)."""
    try:
        import qrcode  # type: ignore
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        from io import StringIO
        buf = StringIO()
        qr.print_ascii(out=buf, invert=True)
        console.print(f"[dim]{buf.getvalue()}[/dim]")
    except ImportError:
        console.print(f"  [dim]QR: {url}[/dim]")


# ── Default callback ───────────────────────────────────────────────────────────

@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", "-v", help="Show version and exit."),
) -> None:
    """Launch the HomeHost TUI. Run [bold]homehost --help[/bold] for CLI commands."""
    if version:
        from homehost import __version__
        rprint(f"[bold blue]HomeHost[/bold blue] v{__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        try:
            from homehost.tui.app import HomeHostApp
            HomeHostApp().run()
        except ImportError as e:
            err_console.print(f"[red]TUI not available:[/red] {e}")
            err_console.print("Run [bold]homehost status[/bold] for a non-TUI view.")
            raise typer.Exit(1)


# ── init ───────────────────────────────────────────────────────────────────────

@app.command()
def init(
    path: Optional[Path] = typer.Argument(None, help="Project directory (default: current directory)."),
    type_: Optional[str] = typer.Option(None, "--type", "-t", help="Project type (static, flask, fastapi, django, nextjs, react, node, docker, custom)."),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Project name (default: directory name)."),
) -> None:
    """Initialize a new HomeHost project in PATH (default: current directory)."""
    try:
        from homehost.core.config import (
            ProjectConfig, ProjectServerConfig, ProjectNetworkConfig,
            list_projects, save_project_config,
        )
        from homehost.core.project import detect_project_type, validate_project_directory, ProjectType
        from homehost.core.detector import find_available_port

        target = (path or Path.cwd()).resolve()
        project_name = name or target.name

        ok, err_msg = validate_project_directory(target)
        if not ok:
            err_console.print(f"[red]Invalid directory:[/red] {err_msg}")
            raise typer.Exit(1)

        if project_name in list_projects():
            err_console.print(
                f"[yellow]Project '[bold]{project_name}[/bold]' is already registered.[/yellow]\n"
                "Use [bold]homehost config[/bold] to modify its settings."
            )
            raise typer.Exit(1)

        # Detect or use specified type
        if type_:
            try:
                ptype = ProjectType(type_.lower())
                detection_msg = f"Using specified type: [bold]{ptype.label}[/bold]"
            except ValueError:
                valid = ", ".join(t.value for t in ProjectType)
                err_console.print(f"[red]Unknown type '[/red]{type_}[red]'.[/red] Valid options: {valid}")
                raise typer.Exit(1)
        else:
            with console.status("[blue]Detecting project type…[/blue]"):
                result = detect_project_type(target)
            ptype = result.project_type
            confidence_color = {"certain": "green", "probable": "yellow", "guessed": "dim"}.get(
                result.confidence, "white"
            )
            detection_msg = (
                f"Detected [{confidence_color}]{ptype.label}[/{confidence_color}] "
                f"[dim]({result.confidence})[/dim] — {result.reason}"
            )

        # Scaffold if empty and type is specified
        is_empty = not any(target.iterdir())
        if is_empty and type_:
            with console.status(f"[blue]Scaffolding {ptype.label} template…[/blue]"):
                _scaffold_project(target, ptype)
            console.print(f"  [green]✓[/green] Scaffolded {ptype.label} template in {target}")

        # Assign a free port
        free_port = find_available_port(8080, 8099) or ptype.default_port

        # Build and save config
        cfg = ProjectConfig(
            name=project_name,
            type=ptype.value,
            path=str(target),
            created=datetime.now(timezone.utc).isoformat(),
        )
        cfg.server = ProjectServerConfig(
            port=free_port,
            auto_start=True,
            build_command=ptype.default_build_command,
            start_command=ptype.default_start_command,
            output_directory="",
        )
        cfg.network = ProjectNetworkConfig(access="local")

        with console.status("[blue]Saving project config…[/blue]"):
            save_project_config(cfg)

        console.print(
            Panel(
                f"[green]Project initialized![/green]\n\n"
                f"  [bold]Name:[/bold]  {project_name}\n"
                f"  [bold]Type:[/bold]  {detection_msg}\n"
                f"  [bold]Path:[/bold]  {target}\n"
                f"  [bold]Port:[/bold]  {free_port}\n"
                f"  [bold]URL:[/bold]   http://localhost:{free_port}\n\n"
                "Run [bold]homehost start[/bold] to launch your server.",
                title="[blue]homehost init[/blue]",
                border_style="blue",
            )
        )
    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-001")


def _scaffold_project(target: Path, ptype) -> None:
    """Create minimal starter files for a given project type."""
    from homehost.core.project import ProjectType

    if ptype == ProjectType.STATIC:
        (target / "index.html").write_text(
            '<!DOCTYPE html>\n<html lang="en">\n<head><meta charset="UTF-8">'
            '<title>My HomeHost Site</title></head>\n'
            '<body><h1>Hello from HomeHost!</h1></body>\n</html>\n',
            encoding="utf-8",
        )
    elif ptype in (ProjectType.FLASK, ProjectType.FASTAPI, ProjectType.DJANGO):
        (target / "requirements.txt").write_text(
            f"{ptype.value}\n", encoding="utf-8"
        )
        if ptype == ProjectType.FLASK:
            (target / "app.py").write_text(
                "from flask import Flask\napp = Flask(__name__)\n\n"
                "@app.route('/')\ndef index():\n    return '<h1>Hello from HomeHost + Flask!</h1>'\n",
                encoding="utf-8",
            )
        elif ptype == ProjectType.FASTAPI:
            (target / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n\n"
                "@app.get('/')\ndef root():\n    return {'message': 'Hello from HomeHost + FastAPI!'}\n",
                encoding="utf-8",
            )
    elif ptype in (ProjectType.NEXTJS, ProjectType.REACT, ProjectType.NODE):
        (target / "package.json").write_text(
            '{\n  "name": "homehost-app",\n  "version": "1.0.0",\n'
            '  "scripts": {"start": "node index.js"}\n}\n',
            encoding="utf-8",
        )
        (target / "index.js").write_text(
            "const http = require('http');\n"
            "http.createServer((req, res) => {\n"
            "  res.end('<h1>Hello from HomeHost + Node!</h1>');\n"
            "}).listen(3000, () => console.log('Running on port 3000'));\n",
            encoding="utf-8",
        )


# ── start ──────────────────────────────────────────────────────────────────────

@app.command()
def start(
    project: Optional[str] = typer.Argument(None, help="Project name (default: current directory)."),
) -> None:
    """Start the server for a project."""
    try:
        from homehost.core.config import load_project_config, list_projects
        from homehost.core.process import ProcessManager, ProcessState
        from homehost.core.detector import get_local_ip

        name = _resolve_project_name(project)

        if not _project_exists(name):
            err_console.print(
                f"[yellow]Project '[bold]{name}[/bold]' is not registered.[/yellow]\n"
                "Run [bold]homehost init[/bold] to set it up first."
            )
            raise typer.Exit(1)

        cfg = load_project_config(name)
        pm = _get_process_manager()

        if pm.is_running(name):
            console.print(f"[yellow]Project '[bold]{name}[/bold]' is already running.[/yellow]")
            console.print(f"  URL: [bold blue]http://localhost:{cfg.server.port}[/bold blue]")
            return

        project_path = Path(cfg.path)
        if not project_path.exists():
            err_console.print(f"[red]Project directory not found:[/red] {project_path}")
            raise typer.Exit(1)

        # Build step
        if cfg.server.build_command:
            with console.status(f"[blue]Building {name}…[/blue]"):
                ret = subprocess.run(
                    cfg.server.build_command,
                    shell=True,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                )
            if ret.returncode != 0:
                err_console.print(
                    Panel(
                        f"[red]Build failed[/red] (exit {ret.returncode})\n\n"
                        f"[dim]{ret.stderr[-1000:]}[/dim]",
                        title="[red]Build Error[/red]",
                        border_style="red",
                    )
                )
                raise typer.Exit(1)
            console.print(f"  [green]✓[/green] Build complete")

        # Start step
        if cfg.server.start_command:
            command = cfg.server.start_command.split()
        else:
            # Fallback: static file server via Python
            command = [
                sys.executable, "-m", "http.server", str(cfg.server.port),
                "--directory", str(project_path),
            ]

        with console.status(f"[blue]Starting {name}…[/blue]"):
            log_file = _log_dir() / f"{name}.log"
            pm.start(name, command, cwd=project_path, log_file=log_file)
            time.sleep(1.2)  # brief pause to let process settle

        local_url = f"http://localhost:{cfg.server.port}"
        lan_url = f"http://{get_local_ip()}:{cfg.server.port}"

        console.print(
            Panel(
                f"[green]Server started![/green]\n\n"
                f"  [bold]Local:[/bold]   {local_url}\n"
                f"  [bold]Network:[/bold] {lan_url}\n\n"
                f"Logs: [dim]{log_file}[/dim]\n"
                "Stop with [bold]homehost stop[/bold]",
                title=f"[blue]{name}[/blue]",
                border_style="green",
            )
        )
        _print_qr(local_url)

    except typer.Exit:
        raise
    except RuntimeError as exc:
        err_console.print(f"[red]Start failed:[/red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        handle_error(exc, "HH-002")


@app.command()
def serve(
    path: Optional[Path] = typer.Argument(None, help="Directory to serve (default: current directory)."),
    port: Optional[int] = typer.Option(None, "--port", "-p", help="Port to listen on (default: auto-pick 8080-8099)."),
    public: bool = typer.Option(False, "--public", help="Start a free Cloudflare Tunnel for public internet access."),
    type_: Optional[str] = typer.Option(None, "--type", "-t", metavar="TYPE",
                                         help="Force project type: static, flask, fastapi, django, nextjs, react, node."),
    no_reload: bool = typer.Option(False, "--no-reload", help="Disable file-change auto-reload."),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Project name (default: directory name)."),
) -> None:
    """Detect, register, and serve a project directory in one step.

    This is the recommended first-time command. Press Ctrl+C to stop.

    Examples:

      homehost serve .
      homehost serve ~/my-site --public
      homehost serve . --port 3000 --type flask
    """
    import signal

    try:
        from homehost.core.config import (
            load_project_config, save_project_config, ProjectConfig,
            ProjectServerConfig, ProjectNetworkConfig, ProjectWatcherConfig,
            ProjectSecurityConfig, projects_dir,
        )
        from homehost.core.project import detect_project_type, validate_project_directory, ProjectType
        from homehost.core.detector import get_local_ip
        from homehost.utils.network import find_free_port, is_port_in_use

        target = Path(path or Path.cwd()).resolve()
        ok, err = validate_project_directory(target)
        if not ok:
            err_console.print(f"[red]Cannot serve directory:[/red] {err}")
            raise typer.Exit(1)

        # ── Detect project type ───────────────────────────────────────────────
        if type_:
            try:
                detected_type = ProjectType(type_.lower())
                detect_label = f"[dim](forced)[/dim]"
            except ValueError:
                err_console.print(
                    f"[red]Unknown project type '{type_}'.[/red] "
                    "Valid: static, flask, fastapi, django, nextjs, react, node, custom"
                )
                raise typer.Exit(1)
        else:
            with console.status("[blue]Detecting project type…[/blue]"):
                result = detect_project_type(target)
            detected_type = result.project_type
            detect_label = f"[dim]({result.reason})[/dim]"

        console.print(f"  [green]✓[/green] Detected: [bold]{detected_type.label}[/bold] {detect_label}")

        # ── Pick or validate port ─────────────────────────────────────────────
        project_name = name or target.name
        chosen_port: int
        if port:
            if is_port_in_use(port):
                err_console.print(
                    f"[red]Port {port} is already in use.[/red] "
                    "Try a different port with --port, or omit --port to auto-pick."
                )
                raise typer.Exit(1)
            chosen_port = port
        else:
            chosen_port = find_free_port(8080, 8099)

        console.print(f"  [green]✓[/green] Port: [bold]{chosen_port}[/bold]")

        # ── Register project (upsert) ─────────────────────────────────────────
        cfg = ProjectConfig()
        cfg.name = project_name
        cfg.type = detected_type.value
        cfg.path = str(target)
        cfg.server = ProjectServerConfig()
        cfg.server.port = chosen_port
        cfg.server.auto_start = True
        cfg.server.build_command = detected_type.default_build_command
        cfg.server.start_command = detected_type.default_start_command
        cfg.network = ProjectNetworkConfig()
        cfg.network.access = "public" if public else "local"
        cfg.security = ProjectSecurityConfig()
        cfg.watcher = ProjectWatcherConfig()
        cfg.watcher.enabled = not no_reload
        save_project_config(cfg)

        # ── Start server ──────────────────────────────────────────────────────
        pm = _get_process_manager()

        if detected_type == ProjectType.STATIC or not cfg.server.start_command:
            command = [sys.executable, "-m", "http.server", str(chosen_port),
                       "--directory", str(target), "--bind", "0.0.0.0"]
        else:
            command = cfg.server.start_command.split()

        log_file = _log_dir() / f"{project_name}.log"
        with console.status("[blue]Starting server…[/blue]"):
            pm.start(project_name, command, cwd=target, log_file=log_file)
            time.sleep(1.5)

        if not pm.is_running(project_name):
            err_console.print(
                Panel(
                    "[red]Server process exited immediately.[/red]\n\n"
                    f"Check logs for details:\n[dim]{log_file}[/dim]\n\n"
                    f"Or run: [bold]homehost logs {project_name}[/bold]",
                    title="[red]Start Failed[/red]",
                    border_style="red",
                )
            )
            raise typer.Exit(1)

        local_url = f"http://localhost:{chosen_port}"
        lan_url = f"http://{get_local_ip()}:{chosen_port}"

        # ── Optional tunnel ───────────────────────────────────────────────────
        public_url = ""
        if public:
            from homehost.core.config import load_global_config
            gcfg = load_global_config()
            cloudflared = gcfg.server.cloudflared_path or "cloudflared"
            if not shutil.which(cloudflared) and cloudflared == "cloudflared":
                console.print(
                    "  [yellow]⚠[/yellow]  cloudflared not installed — skipping public tunnel.\n"
                    "     Install it: [bold]homehost doctor[/bold] will guide you."
                )
            else:
                with console.status("[blue]Starting Cloudflare Tunnel…[/blue]"):
                    try:
                        from homehost.network.tunnel import TunnelManager
                        tm = TunnelManager(cloudflared, pm)
                        info = tm.start_quick_tunnel(f"{project_name}_tunnel", chosen_port)
                        public_url = info.url
                        cfg.network.subdomain = public_url
                        save_project_config(cfg)
                        console.print(f"  [green]✓[/green] Tunnel: [bold blue]{public_url}[/bold blue]")
                    except Exception as exc:
                        console.print(f"  [yellow]⚠[/yellow]  Tunnel failed: {exc}")

        # ── Status panel ──────────────────────────────────────────────────────
        body = f"  [bold]Local:[/bold]    {local_url}\n"
        body += f"  [bold]Network:[/bold]  {lan_url}  [dim](devices on same Wi-Fi)[/dim]\n"
        if public_url:
            body += f"  [bold]Public:[/bold]   [bold blue]{public_url}[/bold blue]\n"
        body += f"\n  [dim]Logs: {log_file}[/dim]"
        body += "\n\n  Press [bold]Ctrl+C[/bold] to stop."

        console.print(
            Panel(body, title=f"[bold green]✓  {project_name} is running[/bold green]", border_style="green")
        )
        _print_qr(public_url or local_url)

        # ── File watcher ──────────────────────────────────────────────────────
        watcher = None
        if not no_reload and detected_type == ProjectType.STATIC:
            try:
                from homehost.deploy.watcher import ProjectWatcher

                def _on_change(paths: list) -> None:
                    console.print(f"  [blue]♻[/blue]  File change detected — reloading…")

                watcher = ProjectWatcher(target, _on_change)
                watcher.start()
            except Exception:
                pass  # watcher is optional

        # ── Block until Ctrl+C ────────────────────────────────────────────────
        try:
            while pm.is_running(project_name):
                time.sleep(1)
            console.print(f"\n[yellow]Server process stopped unexpectedly.[/yellow] "
                          f"Check logs: [dim]{log_file}[/dim]")
        except KeyboardInterrupt:
            console.print(f"\n[yellow]Stopping {project_name}…[/yellow]")
            pm.stop(project_name)
            if public_url:
                pm.stop(f"{project_name}_tunnel")
            if watcher:
                watcher.stop()
            console.print("[green]Stopped.[/green]")

    except typer.Exit:
        raise
    except RuntimeError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    except Exception as exc:
        handle_error(exc, "HH-014")


# ── stop ───────────────────────────────────────────────────────────────────────

@app.command()
def stop(
    project: Optional[str] = typer.Argument(None, help="Project name (default: current directory)."),
    all_: bool = typer.Option(False, "--all", "-a", help="Stop ALL running projects."),
) -> None:
    """Stop the server for a project (or all projects with --all)."""
    try:
        pm = _get_process_manager()

        if all_:
            processes = pm.list_processes()
            running = [p for p in processes if p.state.value == "running"]
            if not running:
                console.print("[yellow]No running projects.[/yellow]")
                return
            with console.status("[blue]Stopping all projects…[/blue]"):
                pm.stop_all()
            console.print(f"[green]Stopped {len(running)} project(s).[/green]")
            return

        name = _resolve_project_name(project)

        if not pm.is_running(name):
            console.print(f"[yellow]Project '[bold]{name}[/bold]' is not running.[/yellow]")
            return

        with console.status(f"[blue]Stopping {name}…[/blue]"):
            pm.stop(name)

        console.print(f"[green]✓[/green] Project '[bold]{name}[/bold]' stopped.")

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-003")


# ── restart ────────────────────────────────────────────────────────────────────

@app.command()
def restart(
    project: Optional[str] = typer.Argument(None, help="Project name (default: current directory)."),
) -> None:
    """Stop and restart a project's server."""
    try:
        name = _resolve_project_name(project)

        if not _project_exists(name):
            err_console.print(
                f"[yellow]Project '[bold]{name}[/bold]' is not registered.[/yellow]\n"
                "Run [bold]homehost init[/bold] to set it up first."
            )
            raise typer.Exit(1)

        pm = _get_process_manager()

        if pm.is_running(name):
            with console.status(f"[blue]Stopping {name}…[/blue]"):
                pm.stop(name)
            console.print(f"  [yellow]↓[/yellow] Stopped")

        # Re-delegate to start command logic
        ctx = typer.get_current_context()
        ctx.invoke(start, project=name)

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-004")


# ── status ─────────────────────────────────────────────────────────────────────

@app.command()
def status() -> None:
    """Show status of all HomeHost projects."""
    try:
        from homehost.core.config import list_projects, load_project_config

        projects = list_projects()
        if not projects:
            rprint(
                "[yellow]No projects found.[/yellow] "
                "Run [bold]homehost init[/bold] to set up your first project."
            )
            return

        pm = _get_process_manager()
        all_procs = {p.name: p for p in pm.list_processes()}

        table = Table(
            title="HomeHost Projects",
            show_header=True,
            header_style="bold blue",
            border_style="blue",
        )
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Port", justify="right")
        table.add_column("URL")
        table.add_column("Uptime")

        for proj_name in projects:
            try:
                cfg = load_project_config(proj_name)
            except Exception:
                table.add_row(proj_name, "[red]config error[/red]", "?", "?", "?", "?")
                continue

            proc = all_procs.get(proj_name)
            is_running = proc is not None and proc.state.value == "running"

            status_str = "[green]● running[/green]" if is_running else "[dim]○ stopped[/dim]"
            url_str = f"http://localhost:{cfg.server.port}" if is_running else "[dim]—[/dim]"
            uptime_str = _uptime_str(proc.start_time) if (is_running and proc) else "[dim]—[/dim]"

            table.add_row(
                cfg.name,
                cfg.type,
                status_str,
                str(cfg.server.port),
                url_str,
                uptime_str,
            )

        console.print(table)

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-005")


# ── list ───────────────────────────────────────────────────────────────────────

@app.command(name="list")
def list_projects_cmd() -> None:
    """List all registered HomeHost projects."""
    try:
        from homehost.core.config import list_projects, load_project_config

        projects = list_projects()
        if not projects:
            rprint("[yellow]No projects found.[/yellow] Run [bold]homehost init[/bold] to add one.")
            return

        pm = _get_process_manager()
        all_procs = {p.name: p for p in pm.list_processes()}

        table = Table(show_header=True, header_style="bold blue", border_style="dim")
        table.add_column("Name", style="bold")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Path", style="dim")

        for proj_name in projects:
            try:
                cfg = load_project_config(proj_name)
            except Exception:
                table.add_row(proj_name, "[red]?[/red]", "[red]config error[/red]", "?")
                continue

            proc = all_procs.get(proj_name)
            is_running = proc is not None and proc.state.value == "running"
            status_str = "[green]running[/green]" if is_running else "[dim]stopped[/dim]"

            table.add_row(cfg.name, cfg.type, status_str, cfg.path)

        console.print(table)

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-006")


# ── logs ───────────────────────────────────────────────────────────────────────

@app.command()
def logs(
    project: Optional[str] = typer.Argument(None, help="Project name (default: current directory)."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream log output continuously."),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of recent lines to show."),
) -> None:
    """Tail logs for a project. Use --follow to stream continuously."""
    try:
        name = _resolve_project_name(project)
        log_file = _log_dir() / f"{name}.log"

        if not log_file.exists():
            err_console.print(
                f"[yellow]No log file found for '[bold]{name}[/bold]'.[/yellow]\n"
                f"Expected: [dim]{log_file}[/dim]"
            )
            raise typer.Exit(1)

        console.print(
            f"[dim]Logs for [bold]{name}[/bold] — {log_file}[/dim]"
        )
        console.rule(style="dim")

        if follow:
            # Stream tail -f style
            try:
                proc = subprocess.Popen(
                    ["tail", "-n", str(lines), "-f", str(log_file)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    console.print(line, end="")
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped following logs.[/dim]")
        else:
            # Print last N lines
            with open(log_file, encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:]
            for line in tail:
                console.print(line, end="")

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-007")


# ── dashboard ──────────────────────────────────────────────────────────────────

@app.command()
def dashboard() -> None:
    """Open the HomeHost dashboard in your browser, starting it if needed."""
    try:
        from homehost.core.config import load_global_config

        cfg = load_global_config()
        port = cfg.general.dashboard_port
        url = f"http://localhost:{port}"

        pm = _get_process_manager()

        if not pm.is_running("homehost-dashboard"):
            with console.status("[blue]Starting dashboard…[/blue]"):
                try:
                    from homehost.dashboard import app as dashboard_app  # type: ignore
                    dashboard_cmd = [
                        sys.executable, "-m", "homehost.dashboard",
                        "--port", str(port),
                    ]
                    log_file = _log_dir() / "dashboard.log"
                    pm.start(
                        "homehost-dashboard",
                        dashboard_cmd,
                        cwd=Path.home(),
                        log_file=log_file,
                    )
                    time.sleep(1.5)
                    console.print(f"  [green]✓[/green] Dashboard started on port {port}")
                except (ImportError, RuntimeError) as e:
                    console.print(f"  [yellow]Warning:[/yellow] Could not auto-start dashboard: {e}")
                    console.print(f"  Opening {url} anyway…")

        console.print(f"[blue]Opening dashboard:[/blue] {url}")
        webbrowser.open(url)

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-008")


# ── tunnel ─────────────────────────────────────────────────────────────────────

@app.command()
def tunnel(
    project: Optional[str] = typer.Argument(None, help="Project name (default: current directory)."),
    stop_: bool = typer.Option(False, "--stop", help="Stop the tunnel instead of starting it."),
) -> None:
    """Start or stop a public tunnel for a project via cloudflared."""
    try:
        from homehost.core.config import load_project_config
        from homehost.core.detector import find_executable

        name = _resolve_project_name(project)

        if not _project_exists(name):
            err_console.print(
                f"[yellow]Project '[bold]{name}[/bold]' is not registered.[/yellow]"
            )
            raise typer.Exit(1)

        cfg = load_project_config(name)
        pm = _get_process_manager()
        tunnel_proc_name = f"{name}-tunnel"

        if stop_:
            if not pm.is_running(tunnel_proc_name):
                console.print(f"[yellow]No tunnel running for '[bold]{name}[/bold]'.[/yellow]")
                return
            with console.status(f"[blue]Stopping tunnel for {name}…[/blue]"):
                pm.stop(tunnel_proc_name)
            console.print(f"[green]✓[/green] Tunnel stopped for '[bold]{name}[/bold]'.")
            return

        cloudflared = find_executable("cloudflared")
        if not cloudflared:
            err_console.print(
                Panel(
                    "[red]cloudflared not found.[/red]\n\n"
                    "Install it from [link=https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation]"
                    "developers.cloudflare.com[/link]\n"
                    "macOS: [bold]brew install cloudflare/cloudflare/cloudflared[/bold]",
                    title="[red]Missing Dependency[/red]",
                    border_style="red",
                )
            )
            raise typer.Exit(1)

        if pm.is_running(tunnel_proc_name):
            console.print(f"[yellow]Tunnel already running for '[bold]{name}[/bold]'.[/yellow]")
            return

        port = cfg.server.port
        command = [cloudflared, "tunnel", "--url", f"http://localhost:{port}"]

        with console.status(f"[blue]Starting tunnel for {name} on port {port}…[/blue]"):
            log_file = _log_dir() / f"{tunnel_proc_name}.log"
            pm.start(tunnel_proc_name, command, cwd=Path(cfg.path), log_file=log_file)
            time.sleep(2)

        console.print(
            Panel(
                f"[green]Tunnel started![/green]\n\n"
                f"  Forwarding [bold]public URL → localhost:{port}[/bold]\n\n"
                f"  Check the tunnel logs for your public URL:\n"
                f"  [bold]homehost logs {name}-tunnel[/bold]\n\n"
                "Stop with [bold]homehost tunnel --stop[/bold]",
                title=f"[blue]Tunnel — {name}[/blue]",
                border_style="green",
            )
        )

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-009")


# ── config ─────────────────────────────────────────────────────────────────────

@app.command()
def config(
    project: Optional[str] = typer.Argument(None, help="Project name (omit for global config)."),
    edit: bool = typer.Option(False, "--edit", "-e", help="Open config file in $EDITOR."),
) -> None:
    """View or edit global or project config."""
    try:
        from homehost.core.config import (
            global_config_path, project_config_path,
            load_global_config, load_project_config,
        )

        if project:
            if not _project_exists(project):
                err_console.print(f"[yellow]Project '[bold]{project}[/bold]' is not registered.[/yellow]")
                raise typer.Exit(1)
            config_file = project_config_path(project)
            cfg = load_project_config(project)
            title = f"Config — {project}"
            lines = [
                f"[bold]name:[/bold]           {cfg.name}",
                f"[bold]type:[/bold]           {cfg.type}",
                f"[bold]path:[/bold]           {cfg.path}",
                f"[bold]port:[/bold]           {cfg.server.port}",
                f"[bold]auto_start:[/bold]     {cfg.server.auto_start}",
                f"[bold]build_command:[/bold]  {cfg.server.build_command or '—'}",
                f"[bold]start_command:[/bold]  {cfg.server.start_command or '—'}",
                f"[bold]access:[/bold]         {cfg.network.access}",
                f"[bold]subdomain:[/bold]      {cfg.network.subdomain or '—'}",
                f"[bold]custom_domain:[/bold]  {cfg.network.custom_domain or '—'}",
                f"[bold]basic_auth:[/bold]     {cfg.security.basic_auth}",
                f"[bold]rate_limit:[/bold]     {cfg.security.rate_limit} req/s",
            ]
        else:
            config_file = global_config_path()
            cfg_g = load_global_config()
            title = "Global Config"
            lines = [
                f"[bold]dashboard_port:[/bold]      {cfg_g.general.dashboard_port}",
                f"[bold]port_range:[/bold]          {cfg_g.general.default_port_range}",
                f"[bold]auto_start_on_boot:[/bold]  {cfg_g.general.auto_start_on_boot}",
                f"[bold]check_for_updates:[/bold]   {cfg_g.general.check_for_updates}",
                f"[bold]log_level:[/bold]           {cfg_g.general.log_level}",
                f"[bold]log_retention_days:[/bold]  {cfg_g.general.log_retention_days}",
                f"[bold]server_engine:[/bold]       {cfg_g.server.engine}",
                f"[bold]default_access:[/bold]      {cfg_g.network.default_access}",
                f"[bold]tunnel_provider:[/bold]     {cfg_g.network.tunnel_provider}",
                f"[bold]rate_limit:[/bold]          {cfg_g.security.rate_limit} req/s",
                f"[bold]security_headers:[/bold]    {cfg_g.security.enable_security_headers}",
                f"[bold]dashboard_theme:[/bold]     {cfg_g.dashboard.theme}",
            ]

        if edit:
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
            # Ensure file exists before opening
            if not config_file.exists():
                config_file.parent.mkdir(parents=True, exist_ok=True)
                config_file.touch()
            console.print(f"[blue]Opening config in {editor}…[/blue]")
            subprocess.run([editor, str(config_file)])
        else:
            body = "\n".join(f"  {l}" for l in lines)
            body += f"\n\n[dim]File: {config_file}[/dim]"
            body += "\n[dim]Use --edit to open in $EDITOR[/dim]"
            console.print(Panel(body, title=f"[blue]{title}[/blue]", border_style="blue"))

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-010")


# ── uninstall ──────────────────────────────────────────────────────────────────

@app.command()
def uninstall(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
) -> None:
    """Remove HomeHost configuration and data from this machine."""
    try:
        homehost_dir = Path.home() / ".homehost"
        items = []

        if homehost_dir.exists():
            size_mb = sum(
                f.stat().st_size for f in homehost_dir.rglob("*") if f.is_file()
            ) / (1024 * 1024)
            items.append(f"  [bold]Config & data:[/bold] {homehost_dir}  [dim]({size_mb:.1f} MB)[/dim]")

        if not items:
            console.print("[yellow]Nothing to remove — ~/.homehost does not exist.[/yellow]")
            return

        console.print(
            Panel(
                "The following will be [bold red]permanently deleted[/bold red]:\n\n"
                + "\n".join(items)
                + "\n\n[dim]The homehost package itself is NOT removed.\n"
                "Use [bold]pip uninstall homehost[/bold] to remove the package.[/dim]",
                title="[red]homehost uninstall[/red]",
                border_style="red",
            )
        )

        if not yes:
            confirmed = typer.confirm("Are you sure you want to remove HomeHost data?", default=False)
            if not confirmed:
                console.print("[dim]Aborted. Nothing was changed.[/dim]")
                return

        # Stop all running processes first
        pm = _get_process_manager()
        with console.status("[blue]Stopping all running servers…[/blue]"):
            pm.stop_all()

        with console.status("[blue]Removing HomeHost data…[/blue]"):
            if homehost_dir.exists():
                shutil.rmtree(homehost_dir)

        console.print(
            Panel(
                "[green]HomeHost data removed successfully.[/green]\n\n"
                "To also remove the package:\n"
                "  [bold]pip uninstall homehost[/bold]",
                title="[green]Uninstall complete[/green]",
                border_style="green",
            )
        )

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-011")


# ── doctor ─────────────────────────────────────────────────────────────────────

@app.command()
def doctor() -> None:
    """Run system diagnostics and report any issues."""
    try:
        from homehost.core.detector import run_all_checks, detect_system

        console.print(Panel("[bold]HomeHost Doctor[/bold] — System Diagnostics", style="blue"))

        with console.status("[blue]Running checks…[/blue]"):
            info = detect_system()
            checks = run_all_checks()

        # System info header
        console.print(
            f"\n  [bold]System:[/bold]  {info.os_name} {info.os_version} ({info.arch})\n"
            f"  [bold]Python:[/bold]  {info.python_version}\n"
            f"  [bold]IP:[/bold]      {info.local_ip}\n"
            f"  [bold]Disk:[/bold]    {info.disk_free_gb:.1f} GB free\n"
        )
        console.rule(style="dim")

        status_icons = {
            "ok": "[green]✓[/green]",
            "warning": "[yellow]![/yellow]",
            "error": "[red]✗[/red]",
            "missing": "[dim]○[/dim]",
        }

        issues = 0
        for check in checks:
            icon = status_icons.get(check.status, "?")
            color = {"ok": "green", "warning": "yellow", "error": "red", "missing": "dim"}.get(
                check.status, "white"
            )
            console.print(f"  {icon}  [{color}]{check.name}[/{color}]: {check.message}")
            if check.fix_hint and check.status in ("warning", "error", "missing"):
                console.print(f"     [dim]→ {check.fix_hint}[/dim]")
                issues += 1

        console.rule(style="dim")
        if issues == 0:
            console.print("\n  [green]All checks passed.[/green] HomeHost is ready to go!\n")
        else:
            console.print(
                f"\n  [yellow]{issues} issue(s) found.[/yellow] "
                "Address the hints above for the best experience.\n"
            )

        # Available ports summary
        if info.available_ports:
            port_list = ", ".join(str(p) for p in info.available_ports[:10])
            console.print(f"  [dim]Available ports (8080–8099): {port_list}[/dim]\n")
        else:
            console.print("  [yellow]No free ports found in 8080–8099 range.[/yellow]\n")

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-012")


# ── update ─────────────────────────────────────────────────────────────────────

@app.command()
def update() -> None:
    """Check for and install updates to HomeHost."""
    try:
        from homehost import __version__

        console.print(Panel(
            f"[bold]Current version:[/bold] {__version__}\n\nChecking PyPI for updates…",
            title="[blue]homehost update[/blue]",
            border_style="blue",
        ))

        with console.status("[blue]Fetching latest version from PyPI…[/blue]"):
            result = subprocess.run(
                [sys.executable, "-m", "pip", "index", "versions", "homehost"],
                capture_output=True,
                text=True,
                timeout=30,
            )

        latest = None
        if result.returncode == 0:
            # Parse output: "homehost (0.2.0)"
            for line in result.stdout.splitlines():
                if "homehost" in line.lower() and "(" in line:
                    try:
                        latest = line.split("(")[1].split(")")[0].strip().split(",")[0].strip()
                    except IndexError:
                        pass
                    break

        if latest is None:
            # Fallback: try pip install --dry-run
            console.print("[yellow]Could not determine latest version. Attempting upgrade anyway…[/yellow]")
        elif latest == __version__:
            console.print(f"[green]Already up to date![/green] (v{__version__})")
            return
        else:
            console.print(f"  [bold]Latest version:[/bold] {latest}")
            if not typer.confirm(f"Upgrade homehost {__version__} → {latest}?", default=True):
                console.print("[dim]Update cancelled.[/dim]")
                return

        with console.status("[blue]Installing update…[/blue]"):
            upgrade_result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "homehost"],
                capture_output=True,
                text=True,
                timeout=120,
            )

        if upgrade_result.returncode == 0:
            console.print(
                Panel(
                    "[green]Update complete![/green]\n\n"
                    "Restart homehost to use the new version.",
                    title="[green]Updated[/green]",
                    border_style="green",
                )
            )
        else:
            err_console.print(
                Panel(
                    f"[red]Update failed[/red] (exit {upgrade_result.returncode})\n\n"
                    f"[dim]{upgrade_result.stderr[-800:]}[/dim]\n\n"
                    "Try manually: [bold]pip install --upgrade homehost[/bold]",
                    title="[red]Update Error[/red]",
                    border_style="red",
                )
            )
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except subprocess.TimeoutExpired:
        err_console.print("[red]Update timed out.[/red] Check your internet connection and try again.")
        raise typer.Exit(1)
    except Exception as exc:
        handle_error(exc, "HH-013")


# ── setup ─────────────────────────────────────────────────────────────────────

@app.command()
def setup() -> None:
    """Check your system and install any missing dependencies (Caddy, cloudflared).

    Run this once after installing HomeHost to make sure everything is ready.
    """
    doctor()


# ── new ────────────────────────────────────────────────────────────────────────

@app.command()
def new(
    template: str = typer.Argument(..., help="Template type: static, flask, fastapi, nextjs, react."),
    project_name: str = typer.Argument(..., help="Name for the new project (also used as directory name)."),
    output_dir: Optional[Path] = typer.Option(None, "--dir", "-d",
                                               help="Parent directory (default: current directory)."),
) -> None:
    """Scaffold a new project from a starter template.

    Examples:

      homehost new static my-portfolio
      homehost new flask my-api
      homehost new fastapi my-backend
    """
    try:
        from homehost.deploy.scaffold import scaffold_project, TemplateType

        try:
            tmpl = TemplateType(template.lower())
        except ValueError:
            err_console.print(
                f"[red]Unknown template '{template}'.[/red] "
                "Available: static, flask, fastapi, nextjs, react"
            )
            raise typer.Exit(1)

        parent = (output_dir or Path.cwd()).resolve()
        target = parent / project_name

        if target.exists():
            err_console.print(
                f"[red]Directory '{target}' already exists.[/red] "
                "Choose a different name or delete it first."
            )
            raise typer.Exit(1)

        target.mkdir(parents=True)

        with console.status(f"[blue]Scaffolding {tmpl.value} template…[/blue]"):
            created = scaffold_project(tmpl, target, project_name)

        console.print(
            Panel(
                f"[green]Created {len(created)} files[/green] in [bold]{target}[/bold]\n\n"
                f"Next steps:\n"
                f"  cd {project_name}\n"
                f"  homehost serve .",
                title=f"[green]✓  {project_name} created[/green]",
                border_style="green",
            )
        )
        for f in created[:10]:
            console.print(f"  [dim]{f.relative_to(target)}[/dim]")
        if len(created) > 10:
            console.print(f"  [dim]… and {len(created) - 10} more[/dim]")

    except typer.Exit:
        raise
    except Exception as exc:
        handle_error(exc, "HH-015")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()
