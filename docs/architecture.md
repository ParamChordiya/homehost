# Architecture

This document describes the internal architecture of HomeHost — how its components are organized, how they communicate, and how a user command becomes a live website.

---

## Overview

HomeHost is a Python orchestration layer that manages three external processes — your app server, Caddy, and cloudflared — and provides two observation surfaces: a Textual TUI and a FastAPI web dashboard.

```
┌────────────────────────────────────────────────────────────────────┐
│                          homehost process                          │
│                                                                    │
│  ┌──────────────┐   ┌───────────────────────────────────────────┐ │
│  │   CLI        │   │            Core                           │ │
│  │  (Typer)     │──▶│  config.py  detector.py  project.py      │ │
│  └──────────────┘   │  process.py                              │ │
│                     └──────────────┬──────────────────────────┘ │
│                                    │                              │
│          ┌─────────────────────────┼──────────────────────────┐  │
│          │                         │                          │  │
│          ▼                         ▼                          ▼  │
│  ┌──────────────┐       ┌─────────────────┐       ┌────────────┐ │
│  │  TUI Layer   │       │  Servers Layer  │       │  Network   │ │
│  │  (Textual)   │       │  caddy.py       │       │  Layer     │ │
│  │  app.py      │       │  static.py      │       │  tunnel.py │ │
│  │  screens/    │       │  reverse_proxy  │       │  local.py  │ │
│  │  widgets/    │       │  installer.py   │       │  ssl.py    │ │
│  └──────────────┘       └────────┬────────┘       └─────┬──────┘ │
│                                  │                       │        │
│  ┌──────────────┐       ┌────────┴────────┐       ┌─────┴──────┐ │
│  │  Dashboard   │       │  Security Layer │       │  Utils     │ │
│  │  (FastAPI)   │       │  hardening.py   │       │  logger.py │ │
│  │  api.py      │       │  secrets.py     │       │  platform  │ │
│  │  server.py   │       └─────────────────┘       │  network  │ │
│  └──────────────┘                                 └────────────┘ │
└────────────────────────────────────────────────────────────────────┘
         │                    │                        │
         ▼                    ▼                        ▼
  ┌─────────────┐   ┌──────────────────┐   ┌─────────────────────┐
  │ localhost   │   │  Caddy process   │   │ cloudflared process │
  │ :9111       │   │  (web server /   │   │ (tunnel client)     │
  │ (browser    │   │  reverse proxy)  │   │                     │
  │ dashboard)  │   └────────┬─────────┘   └──────────┬──────────┘
  └─────────────┘            │                        │
                             ▼                        ▼
                    ┌─────────────────┐    ┌──────────────────────┐
                    │  Your App       │    │  Cloudflare Edge     │
                    │  (Flask, Next,  │    │  → Public Internet   │
                    │  React, etc.)   │    │                      │
                    └─────────────────┘    └──────────────────────┘
```

---

## Component Breakdown

### CLI (`homehost/cli.py`)

The CLI is built with [Typer](https://typer.tiangolo.com/). It is intentionally thin — command handlers parse arguments, construct the appropriate `Project` object, and hand off to the `Core` layer. No business logic lives in the CLI.

The CLI exposes these commands: `serve`, `setup`, `doctor`, `new`, `list`, `stop`, `logs`, `config`, `update`, `version`.

### Core (`homehost/core/`)

The Core is the central state machine and orchestration hub.

**`project.py`** — Defines the `Project` dataclass, which is the single source of truth for a running project. It holds the project path, detected type, port, process handles, current status, config, and accumulated log entries.

**`config.py`** — Loads and saves TOML configuration files. Global config from `~/.homehost/config.toml` is merged with project-level config from `<project>/homehost.toml`. Project config takes precedence. Uses `tomllib` (stdlib on 3.11+) for reading and `tomli-w` for writing.

**`detector.py`** — Inspects a directory and returns a `ProjectType` enum value. Detection is ordered from most specific to least specific: Next.js before React, Flask before generic Python, etc. Detection examines file presence (`index.html`, `manage.py`, `next.config.js`), `package.json` dependency lists, and `requirements.txt` / `pyproject.toml` contents.

**`process.py`** — Manages subprocess lifecycles using Python's `asyncio.subprocess`. Provides `start()`, `stop()`, `restart()`, and `health_check()` for each managed process. Captures stdout/stderr and emits log events to listeners. Implements exponential backoff for automatic restarts on crash.

### Servers (`homehost/servers/`)

**`installer.py`** — Downloads and installs Caddy and cloudflared binaries to `~/.homehost/bin/`. Verifies SHA-256 checksums before installing. Handles platform detection (darwin/arm64, darwin/amd64, windows/amd64) to fetch the correct binary.

**`caddy.py`** — The primary server configuration engine. Generates Caddyfiles dynamically based on the `Project` object. Calls `hardening.py` to inject security headers and rate-limit config into every generated Caddyfile. Manages the Caddy process via `process.py`.

**`static.py`** — Helpers for generating Caddy `file_server` directives for static site projects.

**`reverse_proxy.py`** — Helpers for generating Caddy `reverse_proxy` directives for app servers. Handles health-check polling to wait for the upstream app server to become ready before Caddy starts accepting traffic.

### Network (`homehost/network/`)

**`tunnel.py`** — Manages the `cloudflared tunnel --url` subprocess. Parses cloudflared's stdout to extract the assigned public URL. Emits URL-ready and disconnected events to listeners. Supports graceful shutdown.

**`local.py`** — Discovers the machine's LAN IP address (the address accessible to other devices on the same Wi-Fi or Ethernet network). Used to display the "Network: http://192.168.x.x:8080" URL in the TUI.

**`ssl.py`** — Utilities for future local HTTPS support via Caddy's `tls internal` directive. Currently unused; reserved for a future release.

**`firewall.py`** — Checks whether a given port is blocked by the OS firewall and emits a warning if so. macOS uses `pfctl`, Windows uses `netsh`.

**`dns.py`** — DNS resolution utilities, primarily used to verify that the Cloudflare Tunnel subdomain resolves correctly after setup.

### Security (`homehost/security/`)

**`hardening.py`** — Generates the Caddy configuration snippets for security headers and rate limiting. Headers are intentionally strict defaults that work for most projects. Developers can relax them via `homehost.toml` if needed (e.g., to allow cross-origin iframes).

**`secrets.py`** — Handles Basic Auth credential management. Generates bcrypt hashes of passwords for Caddy's `basicauth` directive. Stores hashed credentials in `~/.homehost/auth/<project-name>.toml`.

### TUI (`homehost/tui/`)

**`app.py`** — The root [Textual](https://textual.textualize.io/) application. Manages the overall screen stack and subscribes to events from `Core`. Handles top-level keyboard bindings.

**`screens/`** — Full-screen Textual `Screen` subclasses:
- `welcome.py` — First-run welcome screen
- `setup.py` — Interactive setup wizard screen

**`widgets/`** — Reusable Textual `Widget` subclasses used across multiple screens (log panel, status bar, QR code renderer, traffic sparkline).

### Dashboard (`homehost/dashboard/`)

**`server.py`** — Starts a Uvicorn server in a background thread, exposing the FastAPI application on port 9111. Runs concurrently with the TUI without blocking it.

**`api.py`** — The FastAPI application. Provides REST endpoints:
- `GET /api/projects` — list all running projects
- `GET /api/projects/{name}` — project detail + status
- `POST /api/projects/{name}/tunnel` — toggle tunnel on/off
- `POST /api/projects/{name}/restart` — restart app server
- `GET /api/projects/{name}/logs` — stream logs (Server-Sent Events)
- `GET /api/metrics` — request counts and latency percentiles

**`static/`** — The built web dashboard frontend (HTML/CSS/JS). Served as static files by FastAPI's `StaticFiles` mount.

### Utils (`homehost/utils/`)

**`logger.py`** — Configures `structlog` with a development-friendly console renderer and a JSON renderer for log files. Log files are written to `~/.homehost/logs/homehost.log` with daily rotation.

**`network.py`** — Port availability checking (`is_port_available()`), URL parsing helpers, and retry logic for HTTP health checks.

**`platform.py`** — OS detection, architecture detection, and platform-specific path resolution (e.g., `~/.homehost/bin/caddy` vs `~\.homehost\bin\caddy.exe`).

**`updater.py`** — Checks PyPI for a newer version of HomeHost and prompts the user to update. Also re-runs the binary installer to pick up new Caddy and cloudflared releases.

---

## Data Flow: From Command to Live Website

Here is the exact sequence of events when a user runs `homehost serve ./my-app --public`:

1. **CLI parse** — Typer parses `./my-app` as `path` and `--public` as `tunnel=True`. Calls `serve_command(path, tunnel=True)`.

2. **Config load** — `config.py` reads `~/.homehost/config.toml`, then checks for `./my-app/homehost.toml` and merges project-level overrides.

3. **Detection** — `detector.py` inspects `./my-app`, finds `app.py` and `flask` in `requirements.txt`, returns `ProjectType.FLASK`.

4. **Project creation** — A `Project` object is instantiated with the detected type, the merged config, and `status=STARTING`.

5. **Caddy config** — `caddy.py` calls `hardening.py` to get security header snippets, then generates a Caddyfile:
   ```
   :8080 {
     header Content-Security-Policy "default-src 'self'"
     header Strict-Transport-Security "max-age=31536000"
     ... (other security headers)
     rate_limit {remote_host} 300r/m
     reverse_proxy :5000
   }
   ```

6. **App server start** — `process.py` launches `flask run --port 5000` as a subprocess. Stdout/stderr are captured and emitted as log events.

7. **Health check** — `reverse_proxy.py` polls `http://localhost:5000` with 500ms intervals, waiting until Flask responds 200. Times out after 30 seconds with error `HH-302`.

8. **Caddy start** — Once Flask is healthy, `caddy.py` writes the Caddyfile and starts `caddy run --config /tmp/homehost-my-app.caddy`. Caddy begins serving on port 8080.

9. **File watcher** — `watchdog` is configured to watch `./my-app` (excluding `__pycache__`, `.git`, `node_modules`). File change events trigger a debounced restart sequence.

10. **TUI launch** — `tui/app.py` takes over the terminal. It subscribes to log events from `process.py` and renders them in the log panel.

11. **Dashboard start** — `dashboard/server.py` starts Uvicorn on port 9111 in a background thread.

12. **Tunnel start** — Because `--public` was passed, `tunnel.py` immediately launches `cloudflared tunnel --url http://localhost:8080`. It watches cloudflared's stdout for the line `Your quick Tunnel has been created!` and extracts the URL.

13. **URL display** — The TUI updates with the public URL and renders the QR code. The web dashboard also reflects the active tunnel.

14. **Steady state** — Caddy handles HTTP traffic, proxying requests to Flask. cloudflared forwards public HTTPS traffic to Caddy. The TUI and dashboard display live logs and metrics.

---

## Config File Structure

### Global config — `~/.homehost/config.toml`

```toml
[defaults]
port = 8080          # Default local port for `homehost serve`
public = false       # Whether to enable tunnel by default
auto_reload = true   # Enable file watcher by default
tui = true           # Show TUI by default (false = log-only mode)

[dashboard]
port = 9111          # Port for the web dashboard
enabled = true

[security]
rate_limit_rpm = 300  # Rate limit per IP in requests per minute
```

### Project config — `<project>/homehost.toml`

```toml
[project]
name = "my-app"             # Display name (defaults to directory name)
type = "flask"              # Force a specific project type
port = 5000                 # Port your app server binds to
env_file = ".env"           # Load these env vars before starting the app

[serve]
start_command = "flask run --port 5000"   # Override the default start command
watch_paths = ["app/", "templates/"]      # Limit file watching to these paths
ignore_patterns = ["*.pyc", "*.log"]     # Additional ignore patterns

[security]
rate_limit_rpm = 600        # Override the global rate limit for this project
csp = "default-src 'self'; img-src *"   # Custom CSP header

[auth]
enabled = false             # Enable HTTP Basic Auth
username = "admin"          # Username (password hash stored separately)
```

---

## Process Management Model

HomeHost manages up to three processes per project:

| Process | Binary | Managed by | Restart policy |
|---|---|---|---|
| App server | Python, Node, etc. | `process.py` | Restart on crash (max 5, then fail) |
| Caddy | `~/.homehost/bin/caddy` | `caddy.py` | Restart on crash (max 3, then fail) |
| cloudflared | `~/.homehost/bin/cloudflared` | `tunnel.py` | Restart on crash (exponential backoff) |

All processes are managed with `asyncio.subprocess`. Process handles are stored on the `Project` object. On `homehost stop`, a `SIGTERM` is sent, followed by `SIGKILL` after a 5-second grace period.

On Windows, `SIGTERM` is not available — HomeHost uses `process.terminate()` which sends `CTRL_BREAK_EVENT` for console processes.

---

## Networking Model

### Local access

Caddy binds to `0.0.0.0:<port>` by default, making the site accessible on both `localhost` and the machine's LAN IP. The LAN IP is discovered by `network/local.py` using a `socket` trick (connecting to `8.8.8.8:80` and reading the local socket address).

### Public access (Cloudflare Tunnel)

The tunnel is entirely outbound. `cloudflared` opens a persistent QUIC connection from your machine to the nearest Cloudflare PoP. Cloudflare assigns a subdomain and routes HTTPS traffic from `*.trycloudflare.com` through this connection to your local Caddy instance. No inbound port forwarding or firewall rules are required.

```
Browser
  │  HTTPS  (TLS terminated at Cloudflare edge)
  ▼
Cloudflare Edge (global PoP)
  │  Encrypted QUIC tunnel (outbound from your machine)
  ▼
cloudflared (your machine)
  │  HTTP (localhost only)
  ▼
Caddy (your machine, port 8080)
  │  HTTP (localhost only)
  ▼
Your App (your machine, port 5000)
```

### Port allocation

HomeHost uses the following ports by default:

| Port | Service | Configurable? |
|---|---|---|
| 8080 | Caddy (web server) | Yes — `--port` flag |
| 9111 | Web dashboard (FastAPI) | Yes — global config |
| 5000 | Flask app server | Yes — project config |
| 3000 | Node/Next.js app server | Yes — project config |
| 8000 | FastAPI/Django app server | Yes — project config |

---

## Security Model

See the dedicated [Security Guide](security.md) for a full discussion. In brief:

- **All user-facing traffic** goes through Caddy, which enforces security headers and rate limiting.
- **The Cloudflare Tunnel** means your machine's IP is never directly exposed.
- **Basic Auth** credentials are hashed with bcrypt before storage.
- **Log files** never contain request bodies or auth credentials.
- **The web dashboard** (port 9111) is bound to `localhost` only and is not accessible from the tunnel or the network.
