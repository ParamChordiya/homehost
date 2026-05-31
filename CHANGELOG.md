# Changelog

All notable changes to HomeHost are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-30

### Added

#### Core
- Initial public release of HomeHost
- `homehost serve <path>` — serve any project from a local directory
- `homehost setup` — interactive first-time setup wizard that installs Caddy and cloudflared
- `homehost doctor` — diagnostic tool that checks the full installation and environment
- `homehost new <template> <name>` — scaffold new projects from built-in starter templates
- `homehost list` — list all currently running HomeHost projects
- `homehost stop <name>` / `homehost stop --all` — stop one or all running projects
- `homehost logs <name>` — stream live logs for a running project
- `homehost config` — open the global config file in your default editor
- `homehost update` — self-update HomeHost and managed binaries
- `homehost version` — print version and dependency information

#### Project Auto-detection
- Automatic project type detection from directory contents (no config required)
- Support for Static HTML/CSS/JS sites
- Support for React apps (Create React App and Vite)
- Support for Next.js apps (Pages Router and App Router)
- Support for Express / generic Node.js servers
- Support for Flask apps
- Support for FastAPI apps
- Support for Django apps
- Support for generic Python apps (`main.py` / `app.py`)
- Manual override via `homehost.toml` in project root

#### Web Server
- Caddy-based web serving with automatic binary management
- Static file serving with directory listings disabled by default
- Reverse proxy mode for app servers
- Automatic Caddy installation on first run (macOS and Windows)
- Automatic Caddy restart on configuration changes

#### Public Tunneling
- Cloudflare Tunnel integration via `cloudflared` for public HTTPS access
- Automatic `cloudflared` binary installation on first run
- Random subdomain generation (`https://<adjective>-<animal>-<n>.trycloudflare.com`)
- Toggle tunnel on/off at runtime from TUI or web dashboard
- Public URL displayed prominently in TUI with QR code

#### TUI Dashboard (Terminal UI)
- Textual-based full-screen TUI with real-time updates
- Live log streaming from Caddy, app server, and cloudflared
- Color-coded request log with method, path, status, and latency
- Project status bar (running / stopped / error)
- Keyboard shortcuts: `t` to toggle tunnel, `r` to restart, `q` to quit, `l` to clear logs
- QR code display for instant mobile access to the public URL
- Multi-project tab view when multiple projects are running

#### Web Dashboard
- FastAPI-backed dashboard at `http://localhost:9111`
- Request log with filtering by status code, method, and path
- Live traffic graph (requests per minute)
- Project configuration viewer and editor
- One-click tunnel toggle
- Process health status for Caddy, app server, and cloudflared
- Log download as plain text

#### File Watcher / Auto-reload
- `watchdog`-based file watcher for all project types
- Debounced restarts to avoid churn during rapid file saves
- Configurable watch paths and ignore patterns per project
- Visual indicator in TUI when a reload is triggered

#### Security
- Automatic security headers on all responses:
  - `Content-Security-Policy` (default-src 'self')
  - `Strict-Transport-Security` (max-age=31536000; includeSubDomains)
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - `Permissions-Policy` (camera=(), microphone=(), geolocation=())
- Rate limiting at 300 requests per minute per IP (configurable)
- Optional HTTP Basic Auth (`homehost serve . --auth`)
- bcrypt password hashing for stored credentials
- No direct IP exposure (traffic routed through Cloudflare Tunnel)

#### Configuration
- Global config at `~/.homehost/config.toml` (auto-created on first run)
- Per-project config via `homehost.toml` in project directory
- Environment variable support via `--env-file` flag (defaults to `.env`)
- All defaults sensible out of the box — config is optional

#### Multi-project Support
- Run multiple projects simultaneously on different ports
- Each project gets its own Caddy process and optional tunnel
- Unified TUI with tab navigation between projects
- Web dashboard shows all projects in a sidebar

#### Starter Templates
- `static` — HTML/CSS/JS starter with responsive layout and modern CSS reset
- `flask` — Flask app with SQLite, Jinja2 templates, and `.env` support
- `fastapi` — FastAPI app with Pydantic models, auto-docs, and async routes
- `nextjs` — Next.js 14 App Router starter with TypeScript and Tailwind CSS
- `react` — React 18 + Vite starter with TypeScript

#### Platform Support
- macOS 12 (Monterey) and later
- Windows 10 and Windows 11
- Python 3.10, 3.11, and 3.12

#### Developer Experience
- Structured logging via `structlog`
- Log files written to `~/.homehost/logs/`
- Descriptive error codes (HH-1xx through HH-5xx) for all failure modes
- `homehost doctor` outputs a shareable diagnostic report

---

[Unreleased]: https://github.com/ParamChordiya/homehost/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ParamChordiya/homehost/releases/tag/v0.1.0
