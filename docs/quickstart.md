# Quick Start Guide

This guide walks you through getting HomeHost installed, serving your first static site, and deploying a Flask app with a live public URL — all in under 15 minutes.

---

## Prerequisites

Before you start, make sure you have:

- **Python 3.10 or higher** — check with `python --version` or `python3 --version`
- **pip** — bundled with Python 3.4+, check with `pip --version`
- **An internet connection** — required for the initial setup (downloading Caddy and cloudflared) and for the Cloudflare Tunnel feature

HomeHost installs [Caddy](https://caddyserver.com/) and [cloudflared](https://github.com/cloudflare/cloudflared) automatically on first run. You do not need to install them yourself.

**Supported operating systems:**

| OS | Version |
|---|---|
| macOS | 12 (Monterey) or later |
| Windows | 10 or 11 |

Linux support is planned for a future release. In the meantime, Linux users can run HomeHost from source.

---

## Installation

### Standard install (recommended)

```bash
pip install homehost
```

### Isolated install with pipx

If you want HomeHost isolated from your system Python environment (recommended for non-developers):

```bash
pip install pipx
pipx install homehost
```

### Verify the installation

```bash
homehost --version
# HomeHost 0.1.0
# Python 3.12.2
# Platform: macOS 14.4.1
```

---

## Step 1: Run the Setup Wizard

The first time you use HomeHost, run the setup wizard. It checks your environment, downloads any missing dependencies, and creates your configuration file.

```bash
homehost setup
```

You will see output like this:

```
HomeHost Setup Wizard
─────────────────────────────────────────────────────
Checking Python version ... OK (3.12.2)
Checking Caddy          ... Not found — installing
  Downloading Caddy 2.7.6 for darwin/arm64 ... done
  Installing to ~/.homehost/bin/caddy      ... done
Checking cloudflared    ... Not found — installing
  Downloading cloudflared for darwin/arm64 ... done
  Installing to ~/.homehost/bin/cloudflared ... done
Writing config          ... ~/.homehost/config.toml
─────────────────────────────────────────────────────
Setup complete. Run `homehost doctor` to verify.
```

If you see any failures, run `homehost doctor` for a detailed diagnostic report. Common issues and fixes are in the [Troubleshooting Guide](troubleshooting.md).

---

## Step 2: Your First Static Site

Let's serve a simple HTML page. If you don't have a project handy, create one now:

```bash
mkdir ~/my-first-site
cd ~/my-first-site

cat > index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>My First HomeHost Site</title>
  <style>
    body { font-family: sans-serif; max-width: 600px; margin: 4rem auto; }
    h1 { color: #2563eb; }
  </style>
</head>
<body>
  <h1>Hello from HomeHost!</h1>
  <p>This page is being served from my laptop.</p>
</body>
</html>
EOF
```

Now serve it:

```bash
homehost serve .
```

HomeHost detects the `index.html` and identifies this as a **Static HTML** project. You'll see the TUI dashboard launch:

```
╔══════════════════════════════════════════════════════════════╗
║  HomeHost v0.1.0                           [q]uit [?]help   ║
╠══════════════════════════════════════════════════════════════╣
║  my-first-site                                               ║
║  ────────────────────────────────────────────────────────   ║
║  Type:     Static HTML                                       ║
║  Local:    http://localhost:8080                             ║
║  Network:  http://192.168.1.42:8080                         ║
║  Public:   (tunnel off — press t to enable)                  ║
║  Status:   ● Running                                         ║
║  Uptime:   0:00:04                                           ║
║  ────────────────────────────────────────────────────────   ║
║  LOGS                                          [r]eload      ║
║  ────────────────────────────────────────────────────────   ║
║  [10:23:01] Caddy started on port 8080                      ║
║  [10:23:02] File watcher active — watching ./               ║
╚══════════════════════════════════════════════════════════════╝
```

Open `http://localhost:8080` in your browser. You should see your "Hello from HomeHost!" page.

### Try auto-reload

Leave HomeHost running. Open `index.html` in a text editor, change the `<h1>` text, and save. Within a second you'll see a reload notification in the TUI:

```
[10:24:15] File changed: index.html — reloading
[10:24:15] Caddy restarted
```

Refresh your browser — the change is live.

---

## Step 3: Your First Flask App

Now let's serve a real web application. First, install Flask if you don't have it:

```bash
pip install flask
```

Create a new project:

```bash
mkdir ~/my-flask-app
cd ~/my-flask-app
```

Or use HomeHost's built-in Flask template:

```bash
homehost new flask my-flask-app
cd my-flask-app
```

The template creates this structure:

```
my-flask-app/
├── app.py
├── requirements.txt
├── .env
└── templates/
    └── index.html
```

`app.py` is a minimal Flask application:

```python
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True)
```

Install the dependencies and serve:

```bash
pip install -r requirements.txt
homehost serve .
```

HomeHost detects the Flask project by finding `app.py` and `flask` in `requirements.txt`. It generates a Caddyfile that reverse-proxies to Flask's built-in dev server:

```
╔══════════════════════════════════════════════════════════════╗
║  HomeHost v0.1.0                           [q]uit [?]help   ║
╠══════════════════════════════════════════════════════════════╣
║  my-flask-app                                                ║
║  ────────────────────────────────────────────────────────   ║
║  Type:     Flask                                             ║
║  Local:    http://localhost:8080                             ║
║  Network:  http://192.168.1.42:8080                         ║
║  Public:   (tunnel off — press t to enable)                  ║
║  Status:   ● Running                                         ║
║  ────────────────────────────────────────────────────────   ║
║  LOGS                                                        ║
║  ────────────────────────────────────────────────────────   ║
║  [10:31:00] Starting Flask dev server on port 5000          ║
║  [10:31:01] Caddy started (reverse proxy → :5000)           ║
║  [10:31:01] File watcher active — watching ./               ║
║  [10:31:04] GET / 200 4ms                                   ║
╚══════════════════════════════════════════════════════════════╝
```

Open `http://localhost:8080` — your Flask app is running behind Caddy with full security headers.

### What about FastAPI?

The flow is identical. Use `homehost new fastapi my-api`, or point HomeHost at any existing FastAPI project. It detects FastAPI via `fastapi` in your `requirements.txt` or `pyproject.toml` and uses `uvicorn` as the ASGI server.

---

## Step 4: Going Public with Cloudflare Tunnel

This is the part that makes HomeHost special. Let's make your Flask app accessible from anywhere on the internet — securely, over HTTPS, with no firewall configuration.

### Enable the tunnel

With your project already running, press `t` in the TUI. Or start with the tunnel enabled from the beginning:

```bash
homehost serve . --public
```

HomeHost launches `cloudflared` and negotiates a tunnel with Cloudflare's edge network. After about 5 seconds you'll see:

```
╔══════════════════════════════════════════════════════════════╗
║  HomeHost v0.1.0                           [q]uit [?]help   ║
╠══════════════════════════════════════════════════════════════╣
║  my-flask-app                                                ║
║  ────────────────────────────────────────────────────────   ║
║  Type:     Flask                                             ║
║  Local:    http://localhost:8080                             ║
║  Network:  http://192.168.1.42:8080                         ║
║  Public:   https://proud-tiger-42.trycloudflare.com   ✅    ║
║  Status:   ● Running                                         ║
║  ────────────────────────────────────────────────────────   ║
║  SCAN TO OPEN ON MOBILE:                                    ║
║  █▀▀▀▀▀█ ▀▀█▄ ▀ █▀▀▀▀▀█                                    ║
║  █ ███ █ ▄▀▀ ▄▀ █ ███ █                                    ║
║  █ ▀▀▀ █ ▀█▄▄▀▀ █ ▀▀▀ █                                    ║
║  ▀▀▀▀▀▀▀ ▀ ▀ █▄ ▀▀▀▀▀▀▀                                    ║
╚══════════════════════════════════════════════════════════════╝
```

The URL `https://proud-tiger-42.trycloudflare.com` is publicly accessible right now. Share it in a Slack message, send it to a client, or text it to your phone. Anyone who visits it sees your Flask app.

### How it works (the short version)

`cloudflared` establishes an encrypted, outbound-only connection from your machine to Cloudflare's global edge network. Cloudflare assigns a random subdomain and routes HTTPS traffic from that domain through the tunnel to your local Caddy server. Your IP address is never exposed — all traffic flows through Cloudflare.

### Limitations of the free tunnel

- The URL changes every time you restart HomeHost (it's randomly generated)
- There are no bandwidth or connection guarantees
- Cloudflare's [Terms of Service](https://www.cloudflare.com/terms/) apply
- This is for development and demos, not production traffic

For a stable URL, you can connect a Cloudflare account and configure a named tunnel — but that's outside the scope of this guide.

---

## Step 5: The Web Dashboard

Every running HomeHost instance exposes a web dashboard at `http://localhost:9111`. Open it in your browser.

The dashboard provides:

- **Request log** — every HTTP request with method, path, status code, latency, and source IP
- **Traffic graph** — requests per minute over the last 30 minutes
- **Project overview** — name, type, ports, uptime, and detected configuration
- **Tunnel controls** — toggle the Cloudflare Tunnel on/off with a button
- **Process health** — status of Caddy, your app server, and cloudflared
- **Log viewer** — filterable log output with download option

If you have multiple projects running simultaneously, the left sidebar lists all of them and lets you switch between project views.

---

## Next Steps

Now that you have a working setup, explore more of what HomeHost offers:

### Run multiple projects

```bash
# Terminal 1
cd ~/my-static-site && homehost serve . --port 8080

# Terminal 2
cd ~/my-flask-app && homehost serve . --port 8081
```

Both projects appear in the web dashboard and can have independent tunnels.

### Set up Basic Auth

Password-protect any project:

```bash
homehost serve . --auth
# Enter username: admin
# Enter password: (hidden)
# Confirm password: (hidden)
# Basic auth enabled.
```

### Check your installation health

```bash
homehost doctor
```

The doctor command checks Python version, binary paths, port availability, network connectivity, and config file integrity. It prints a summary report you can paste into a GitHub issue if something's wrong.

### Explore the CLI

```bash
homehost --help                  # All commands
homehost serve --help            # All flags for `serve`
homehost new --help              # Available templates
```

### Read more

- [Architecture Guide](architecture.md) — deep dive into how HomeHost works
- [Security Guide](security.md) — what HomeHost secures and what it doesn't
- [Troubleshooting Guide](troubleshooting.md) — error codes and common fixes
- [GitHub Issues](https://github.com/ParamChordiya/homehost/issues) — report bugs or request features
