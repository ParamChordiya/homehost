```
 _    _                      _   _           _
| |  | |                    | | | |         | |
| |__| | ___  _ __ ___   ___| |_| | ___  ___| |_
|  __  |/ _ \| '_ ` _ \ / _ \ __| |/ _ \/ __| __|
| |  | | (_) | | | | | |  __/ |_| | (_) \__ \ |_
|_|  |_|\___/|_| |_| |_|\___|\__|_|\___/|___/\__|
```

**Turn your laptop into a web server in 3 minutes.**

[![CI](https://img.shields.io/github/actions/workflow/status/ParamChordiya/homehost/ci.yml?branch=main&label=CI&logo=github)](https://github.com/ParamChordiya/homehost/actions)
[![PyPI](https://img.shields.io/pypi/v/homehost?logo=pypi&logoColor=white)](https://pypi.org/project/homehost/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?logo=python&logoColor=white)](https://pypi.org/project/homehost/)

HomeHost is an open-source CLI tool that lets you host websites and web apps directly from your laptop — no cloud account, no credit card, no DevOps degree required. It auto-detects your project type, configures [Caddy](https://caddyserver.com/) as your web server, and optionally creates a free [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) so anyone on the internet can reach your site.

---

## The 3-Minute Golden Path

```bash
# 1. Install
pip install homehost

# 2. (First time only) check your system
homehost setup

# 3. Point it at your project and serve
cd ~/my-website
homehost serve .

# You'll see:
#
#  ✓ Detected: Static HTML/CSS/JS (Found index.html)
#  ✓ Port: 8080
#
#  ╭──────────────── ✓  my-website is running ────────────────╮
#  │   Local:    http://localhost:8080                        │
#  │   Network:  http://192.168.1.42:8080  (same Wi-Fi)      │
#  │                                                          │
#  │   Press Ctrl+C to stop.                                  │
#  ╰──────────────────────────────────────────────────────────╯
#
#  [QR code for mobile access]
```

Want it public? Add `--public`:

```bash
homehost serve . --public

#  ╭──────────────── ✓  my-website is running ────────────────╮
#  │   Local:    http://localhost:8080                        │
#  │   Network:  http://192.168.1.42:8080                     │
#  │   Public:   https://proud-tiger-42.trycloudflare.com     │
#  ╰──────────────────────────────────────────────────────────╯
```

Share the public URL with anyone. It works immediately, with HTTPS, from any device.

---

## Installation

### macOS / Linux

```bash
pip install homehost
```

### Windows

```powershell
pip install homehost
```

> **Windows PATH note:** If `homehost` isn't found after install, run:
> ```powershell
> python -m homehost --version
> ```
> If that works, add Python's Scripts folder to your PATH:
> ```powershell
> # Find the Scripts path
> python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
> # Then add that path to your System Environment Variables → PATH
> ```
> Or install with [pipx](https://pypa.github.io/pipx/) which handles PATH automatically:
> ```powershell
> pip install pipx
> pipx install homehost
> ```

**Requirements:** Python 3.10+, macOS 12+ or Windows 10/11.

HomeHost automatically installs [Caddy](https://caddyserver.com/) and [cloudflared](https://github.com/cloudflare/cloudflared) when you first run `homehost setup`.

---

## Quick Start

### Step 1 — Install

```bash
pip install homehost
```

### Step 2 — Check your system (first time only)

```bash
homehost setup
```

This runs `homehost doctor` to verify your environment and show how to install Caddy and cloudflared if they're missing. Output looks like:

```
  ✓  python: Python 3.12.2
  ✓  internet: Internet reachable
  ✓  disk: 20.0 GB free
  ✓  node: Node.js 22.1.0
  ○  caddy: Caddy not found
     → Install: brew install caddy  (macOS)
     → Install: winget install CaddyServer.Caddy  (Windows)
  ○  cloudflared: not found (needed for --public tunnels)
     → Install: brew install cloudflared  (macOS)
```

### Step 3 — Serve your project

```bash
cd /path/to/your/project
homehost serve .
```

HomeHost auto-detects your project type and starts the right server. Press **Ctrl+C** to stop.

### Step 4 — Go public (optional)

```bash
homehost serve . --public
```

Creates a free `https://*.trycloudflare.com` URL (no account required). Share it anywhere.

### Step 5 — Open the web dashboard

Navigate to **http://localhost:9111** while a project is running. You'll find project status, request logs, and traffic graphs.

---

## CLI Reference

### `homehost serve` — the main command

```
homehost serve [PATH] [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `PATH` | `.` (current dir) | Project directory to serve |
| `--port`, `-p` | auto (8080–8099) | Port to listen on |
| `--public` | off | Start a free Cloudflare Tunnel for internet access |
| `--type`, `-t` | auto-detected | Force project type: `static`, `flask`, `fastapi`, `django`, `nextjs`, `react`, `node` |
| `--name`, `-n` | directory name | Override the project display name |
| `--no-reload` | off | Disable file-change auto-reload |

**Examples:**

```bash
homehost serve .                              # serve current directory
homehost serve ~/my-site                      # serve a specific path
homehost serve . --public                     # with public tunnel
homehost serve . --port 3000                  # on a specific port
homehost serve . --type flask                 # force project type
homehost serve . --public --no-reload         # public, no auto-reload
```

### All commands

| Command | Description |
|---|---|
| `homehost serve [path]` | **Main command.** Detect, register, and start serving a directory. |
| `homehost serve [path] --public` | Start with a free Cloudflare Tunnel (public internet access) |
| `homehost setup` | Check system dependencies and show how to install missing ones |
| `homehost doctor` | Detailed system diagnostics |
| `homehost new <template> <name>` | Scaffold a new project from a starter template |
| `homehost start [project]` | Start a previously-registered project by name |
| `homehost stop [project]` | Stop a running project |
| `homehost stop --all` | Stop all running projects |
| `homehost restart [project]` | Restart a project |
| `homehost status` | Table view of all registered projects and their status |
| `homehost list` | Short list of all projects |
| `homehost logs [project]` | Stream logs for a project |
| `homehost logs [project] --follow` | Live-tail logs |
| `homehost dashboard` | Open the web dashboard in your browser |
| `homehost config` | Show global config |
| `homehost config [project]` | Show a project's config |
| `homehost tunnel [project]` | Start/stop public tunnel for a registered project |
| `homehost uninstall` | Remove all HomeHost data and config |
| `homehost update` | Update HomeHost to the latest version |
| `homehost --version` | Print version |

---

## Starter Templates

Create a new project from scratch:

```bash
homehost new static my-portfolio    # HTML/CSS/JS starter
homehost new flask my-api           # Flask app
homehost new fastapi my-backend     # FastAPI app with auto-docs
```

Then serve it:

```bash
cd my-portfolio
homehost serve .
```

---

## Supported Project Types

HomeHost auto-detects your project type — no config file needed.

| Type | Detected by | How it's served |
|---|---|---|
| **Static HTML** | `index.html` in root | Python's built-in HTTP server (or Caddy if installed) |
| **Flask** | `requirements.txt` contains `flask` | `flask run` via gunicorn |
| **FastAPI** | `requirements.txt` contains `fastapi` | `uvicorn main:app` |
| **Django** | `requirements.txt` contains `django` | `python manage.py runserver` |
| **Next.js** | `package.json` with `next` dependency | `npx next start` |
| **React** | `package.json` with `vite` or `react-scripts` | `npm start` |
| **Node.js** | `package.json` without a specific framework | `npm start` |

Override detection with `--type`:

```bash
homehost serve . --type flask
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your Machine                             │
│                                                                 │
│  Your Files / App                                               │
│        │                                                        │
│        ▼                                                        │
│  ┌──────────────────────────────────────────────┐              │
│  │  Caddy (web server / reverse proxy)          │              │
│  │  - Serves static files                       │              │
│  │  - Proxies Flask / FastAPI / Node apps       │              │
│  │  - Security headers (CSP, HSTS, etc.)        │              │
│  │  - Rate limiting                             │              │
│  └───────────────────────┬──────────────────────┘              │
│                          │                                      │
│  ┌───────────────────────▼──────────────────────┐              │
│  │  cloudflared (optional, --public only)        │              │
│  │  - Encrypted outbound tunnel to Cloudflare   │              │
│  │  - No firewall ports opened                  │              │
│  │  - Free *.trycloudflare.com URL              │              │
│  └───────────────────────┬──────────────────────┘              │
│                          │                                      │
│  HomeHost CLI            │    Web Dashboard                     │
│  homehost serve .   ─────┘    http://localhost:9111             │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
                    Public Internet
```

The tunnel creates an **outbound-only** encrypted connection — your IP address is never exposed directly.

---

## HomeHost vs. the Alternatives

| | HomeHost | Ngrok | LocalTunnel | Vercel |
|---|---|---|---|---|
| **Price** | Free | Freemium | Free | Freemium |
| **Runs on your machine** | ✅ | ✅ | ✅ | ❌ |
| **HTTPS** | ✅ | ✅ | ✅ | ✅ |
| **Custom domains** | ✅ via Cloudflare | 💰 Paid | ❌ | 💰 Paid |
| **Python apps** | ✅ | ✅ | ✅ | ❌ |
| **Auto-detect project type** | ✅ | ❌ | ❌ | ✅ |
| **Exposes your IP** | ❌ | ✅ | ✅ | ❌ |
| **Open source** | ✅ MIT | ❌ | ✅ | ❌ |

---

## Troubleshooting

### `homehost: command not found` (Windows)

Python's Scripts directory isn't in your PATH. Fix it:

```powershell
# Option A — use python -m
python -m homehost serve .

# Option B — install with pipx (adds to PATH automatically)
pip install pipx && pipx install homehost

# Option C — find the Scripts path and add it to PATH manually
python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

### Caddy or cloudflared not installed

Run `homehost setup` — it will show the exact install command for your OS.

### Port already in use

HomeHost auto-picks the next free port in 8080–8099. You can also specify one:

```bash
homehost serve . --port 9000
```

### `--public` tunnel doesn't start

`cloudflared` must be installed. Run `homehost setup` to check. Install manually:

- **macOS:** `brew install cloudflared`
- **Windows:** `winget install Cloudflare.cloudflared`

### Run the full diagnostic

```bash
homehost doctor
```

---

## Contributing

```bash
git clone https://github.com/ParamChordiya/homehost.git
cd homehost
pip install -e ".[dev]"
pytest tests/unit/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  Made with care for developers who were tired of paying for hosting.<br>
  If HomeHost saves you time, consider giving it a ⭐ on <a href="https://github.com/ParamChordiya/homehost">GitHub</a>.
</p>
