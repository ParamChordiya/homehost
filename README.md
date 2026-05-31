```
 _    _                      _   _           _
| |  | |                    | | | |         | |
| |__| | ___  _ __ ___   ___| |_| | ___  ___| |_
|  __  |/ _ \| '_ ` _ \ / _ \ __| |/ _ \/ __| __|
| |  | | (_) | | | | | |  __/ |_| | (_) \__ \ |_
|_|  |_|\___/|_| |_| |_|\___|\__|_|\___/|___/\__|
```

**Turn your laptop into a web server in 3 minutes.**

[![CI](https://img.shields.io/github/actions/workflow/status/homehost-dev/homehost/ci.yml?branch=main&label=CI&logo=github)](https://github.com/homehost-dev/homehost/actions)
[![PyPI](https://img.shields.io/pypi/v/homehost?logo=pypi&logoColor=white)](https://pypi.org/project/homehost/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?logo=python&logoColor=white)](https://pypi.org/project/homehost/)
[![Downloads](https://img.shields.io/pypi/dm/homehost)](https://pypi.org/project/homehost/)

HomeHost is an open-source CLI/TUI tool that lets you host websites and web apps directly from your laptop — no cloud account, no credit card, no DevOps degree required. It automatically configures [Caddy](https://caddyserver.com/) as your web server and [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) for secure public access, wrapping everything in a beautiful terminal dashboard.

---

## The 3-Minute Golden Path

```bash
# Install
pip install homehost

# Point it at your project
cd ~/my-website
homehost serve .

# You'll see something like:
#
#  HomeHost v0.1.0
#  ──────────────────────────────────────────────
#  Local:    http://localhost:8080
#  Public:   https://proud-tiger-42.trycloudflare.com
#  Dashboard http://localhost:9111
#  ──────────────────────────────────────────────
#  Detected: Static HTML site
#  Status:   Running  •  Auto-reload: ON
#
#  Scan to open on your phone:
#  █▀▀▀▀▀█ ▀▀█▄ ▀ █▀▀▀▀▀█
#  █ ███ █ ▄▀▀ ▄▀ █ ███ █
#  █ ▀▀▀ █ ▀█▄▄▀▀ █ ▀▀▀ █
#  ▀▀▀▀▀▀▀ ▀ ▀ █▄ ▀▀▀▀▀▀▀
```

Share the public URL with anyone in the world. They open it in a browser. That's it.

---

## Features

| | Feature | Details |
|---|---|---|
| ⚡ | **Zero-config setup** | Detects your project type automatically and configures everything |
| 🖥️ | **macOS and Windows** | Full support for both platforms, with native installers for dependencies |
| 🗂️ | **Multi-framework support** | Static sites, Next.js, React, Express, Flask, FastAPI, Django |
| 🔒 | **Free HTTPS** | End-to-end encryption via Cloudflare Tunnel — no certificates to manage |
| 🖼️ | **Built-in TUI dashboard** | Real-time logs, request traffic, and process status in your terminal |
| 🌐 | **Web dashboard** | Full browser dashboard at `http://localhost:9111` with request inspector |
| ♻️ | **Auto-reload** | Watches your files and restarts the server on changes |
| 🛡️ | **Security headers** | CSP, HSTS, X-Frame-Options, and rate limiting configured out of the box |
| 📦 | **Multi-project support** | Run multiple sites simultaneously on different ports |
| 📱 | **QR code sharing** | Instantly scan to preview on a mobile device |

---

## Installation

```bash
# Primary (recommended)
pip install homehost

# With pipx for isolated install
pipx install homehost

# macOS (Homebrew) — coming soon
brew install homehost

# Windows (Chocolatey) — coming soon
choco install homehost
```

HomeHost automatically installs [Caddy](https://caddyserver.com/) and [cloudflared](https://github.com/cloudflare/cloudflared) on first run — you don't need to install them yourself.

**Requirements:**
- Python 3.10 or higher
- macOS 12+ or Windows 10/11
- An internet connection (for tunnel setup)

---

## Quick Start

### Step 1 — Install HomeHost

```bash
pip install homehost
```

### Step 2 — Run the setup wizard (first time only)

```bash
homehost setup
```

HomeHost will check for dependencies, install Caddy and cloudflared if they're missing, and write a config file to `~/.homehost/config.toml`. This takes about 60 seconds.

### Step 3 — Serve your project

```bash
cd /path/to/your/project
homehost serve .
```

HomeHost detects your project type (static site, Node.js app, Python app) and starts the appropriate server. You'll see the TUI dashboard launch in your terminal with the local URL.

### Step 4 — Go public

```bash
# Already running? Open the dashboard or press 't' in the TUI to toggle the tunnel.
# Or pass --public when you start:
homehost serve . --public
```

A Cloudflare Tunnel URL like `https://proud-tiger-42.trycloudflare.com` is generated and displayed with a QR code. Share it freely — it works immediately, with HTTPS, from any device on earth.

### Step 5 — Open the web dashboard

Navigate to `http://localhost:9111` in your browser. You'll find a full request log, live traffic graphs, project configuration, and one-click tunnel toggle.

---

## CLI Reference

| Command | Description |
|---|---|
| `homehost serve <path>` | Serve a project from the given directory |
| `homehost serve <path> --port <n>` | Use a specific port (default: 8080) |
| `homehost serve <path> --public` | Start with Cloudflare Tunnel enabled immediately |
| `homehost serve <path> --no-reload` | Disable file watching / auto-reload |
| `homehost setup` | Run the interactive first-time setup wizard |
| `homehost doctor` | Diagnose your installation and environment |
| `homehost list` | List all running HomeHost projects |
| `homehost stop <name>` | Stop a running project by name |
| `homehost stop --all` | Stop all running projects |
| `homehost logs <name>` | Stream logs for a project |
| `homehost config` | Open the config file in your default editor |
| `homehost new <template> <name>` | Scaffold a new project from a starter template |
| `homehost update` | Update HomeHost and its dependencies |
| `homehost version` | Print version information |

### `homehost serve` flags

| Flag | Default | Description |
|---|---|---|
| `--port`, `-p` | `8080` | Local port to bind the web server to |
| `--public` | `false` | Enable Cloudflare Tunnel on start |
| `--no-reload` | `false` | Disable file watcher / auto-reload |
| `--auth` | `false` | Prompt to set up HTTP Basic Auth |
| `--name`, `-n` | directory name | Override the project display name |
| `--env-file` | `.env` | Load environment variables from a file |
| `--tui / --no-tui` | `--tui` | Show or hide the TUI dashboard |

---

## Supported Project Types

HomeHost auto-detects your project type and configures the right server. No `homehost.toml` required.

| Type | Auto-detected by | Dev start command | Build command |
|---|---|---|---|
| **Static HTML** | `index.html` in root | Caddy file server | — |
| **React (CRA / Vite)** | `package.json` + `react` dep | `npm run dev` | `npm run build` |
| **Next.js** | `next.config.*` present | `npm run dev` | `npm run build` |
| **Express / Node** | `package.json` + `express` dep | `node index.js` | — |
| **Flask** | `app.py` + `flask` in requirements | `flask run` | — |
| **FastAPI** | `main.py` + `fastapi` in requirements | `uvicorn main:app --reload` | — |
| **Django** | `manage.py` present | `python manage.py runserver` | — |
| **Generic Node** | `package.json` + `start` script | `npm start` | — |
| **Generic Python** | `main.py` / `app.py` present | `python main.py` | — |

If your project type isn't detected, you can specify it manually in `homehost.toml` at your project root:

```toml
[project]
name = "my-app"
type = "node"
start_command = "node server.js"
port = 3000
```

---

## Starter Templates

Scaffold a new project instantly:

```bash
homehost new static my-portfolio     # HTML/CSS/JS starter
homehost new flask my-api            # Flask app with SQLite
homehost new fastapi my-api          # FastAPI app with auto-docs
homehost new nextjs my-site          # Next.js 14 app router
homehost new react my-app            # React + Vite
```

---

## Architecture

HomeHost is a thin orchestration layer around battle-tested open source tools:

```
┌─────────────────────────────────────────────────────────────────┐
│                        Your Machine                             │
│                                                                 │
│  Your Files                                                     │
│     │                                                           │
│     ▼                                                           │
│  ┌─────────────────┐     ┌──────────────────────────────────┐  │
│  │  Your App       │────▶│  Caddy (web server / proxy)      │  │
│  │  (Flask, Next,  │     │  - Serves static files           │  │
│  │   React, etc.)  │     │  - Reverse-proxies app servers   │  │
│  └─────────────────┘     │  - Security headers              │  │
│                          │  - Rate limiting                  │  │
│  ┌─────────────────┐     └──────────────┬───────────────────┘  │
│  │  HomeHost TUI   │                    │                       │
│  │  - Logs         │     ┌──────────────▼───────────────────┐  │
│  │  - Status       │     │  cloudflared (Cloudflare Tunnel) │  │
│  │  - Controls     │     │  - Encrypted outbound tunnel     │  │
│  └─────────────────┘     │  - No inbound firewall ports     │  │
│                          └──────────────┬───────────────────┘  │
│  ┌─────────────────┐                    │                       │
│  │  Web Dashboard  │                    │                       │
│  │  localhost:9111 │                    │                       │
│  └─────────────────┘                    │                       │
└─────────────────────────────────────────┼───────────────────────┘
                                          │
                                          ▼
                             ┌────────────────────────┐
                             │  Cloudflare Edge       │
                             │  trycloudflare.com     │
                             │  - TLS termination     │
                             │  - DDoS protection     │
                             └────────────┬───────────┘
                                          │
                                          ▼
                                   Public Internet
                                  (anyone, anywhere)
```

The Cloudflare Tunnel creates an outbound-only encrypted connection — you never open firewall ports or expose your IP address directly.

---

## HomeHost vs. the Alternatives

| Feature | HomeHost | Ngrok | LocalTunnel | Vercel |
|---|---|---|---|---|
| **Price** | Free | Freemium | Free | Freemium |
| **Runs on your machine** | ✅ | ✅ | ✅ | ❌ |
| **HTTPS** | ✅ | ✅ | ✅ | ✅ |
| **Custom domains** | ✅ (via Cloudflare) | 💰 Paid | ❌ | 💰 Paid |
| **Static sites** | ✅ | ✅ | ✅ | ✅ |
| **Node.js apps** | ✅ | ✅ | ✅ | ✅ |
| **Python apps** | ✅ | ✅ | ✅ | ❌ |
| **TUI dashboard** | ✅ | ❌ | ❌ | ❌ |
| **Web dashboard** | ✅ | ✅ | ❌ | ✅ |
| **Auto-detect project type** | ✅ | ❌ | ❌ | ✅ |
| **Auto-reload** | ✅ | ❌ | ❌ | ✅ |
| **Security headers** | ✅ Auto | ❌ Manual | ❌ | ✅ Auto |
| **Rate limiting** | ✅ Auto | ❌ | ❌ | 💰 Paid |
| **Exposes your IP** | ❌ | ✅ | ✅ | ❌ |
| **Starter templates** | ✅ | ❌ | ❌ | ✅ |
| **Open source** | ✅ MIT | ❌ | ✅ | ❌ |

---

## Configuration

HomeHost works with zero configuration. When you need to customize, there are two config files:

**Global config** — `~/.homehost/config.toml`
```toml
[defaults]
port = 8080
public = false
auto_reload = true
tui = true

[dashboard]
port = 9111

[security]
rate_limit_rpm = 300
```

**Project config** — `homehost.toml` (in your project directory)
```toml
[project]
name = "my-app"
type = "flask"
port = 5000
env_file = ".env"

[serve]
start_command = "flask run --port 5000"
watch_paths = ["app/", "templates/"]
ignore_patterns = ["*.pyc", "__pycache__"]
```

---

## Contributing

We welcome contributions of all kinds — bug reports, feature requests, documentation improvements, and code. See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

```bash
git clone https://github.com/homehost-dev/homehost.git
cd homehost
pip install -e ".[dev]"
pytest
```

---

## License

HomeHost is released under the [MIT License](LICENSE). Copyright (c) 2026 HomeHost Contributors.

---

<p align="center">
  Made with care by developers who were tired of paying for hosting.
  <br>
  If HomeHost saves you money, consider giving it a ⭐ on GitHub.
</p>
