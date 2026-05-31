# Troubleshooting Guide

This guide covers the most common issues users encounter with HomeHost, organized by error code and by operating system. If you can't find your issue here, run `homehost doctor` and paste the output into a [GitHub Issue](https://github.com/homehost-dev/homehost/issues).

---

## Quick Diagnosis

Before diving into specific issues, run the doctor command:

```bash
homehost doctor
```

The doctor checks:
- Python version and path
- Caddy binary presence and version
- cloudflared binary presence and version
- Global config file validity
- Port availability (8080, 9111)
- Network connectivity (DNS, Cloudflare reachability)
- OS firewall status
- Log file locations and disk space

A healthy output looks like:

```
HomeHost Doctor v0.1.0
────────────────────────────────────────────────────────
✓ Python 3.12.2 at /usr/local/bin/python3
✓ Caddy 2.7.6 at ~/.homehost/bin/caddy
✓ cloudflared 2024.4.1 at ~/.homehost/bin/cloudflared
✓ Config file valid: ~/.homehost/config.toml
✓ Port 8080 available
✓ Port 9111 available
✓ DNS resolution: OK
✓ Cloudflare reachability: OK
✓ macOS firewall: not blocking
✓ Log directory: ~/.homehost/logs/ (24 MB used)
────────────────────────────────────────────────────────
All checks passed. HomeHost is healthy.
```

Any line with `✗` indicates a problem. The doctor will include a suggested fix beneath each failure.

---

## Error Code Reference

HomeHost uses structured error codes in the format `HH-NNN`. The first digit indicates the category:

| Range | Category |
|---|---|
| HH-1xx | Installation and setup errors |
| HH-2xx | Configuration errors |
| HH-3xx | Server startup errors |
| HH-4xx | Network and tunnel errors |
| HH-5xx | Runtime errors |

### HH-1xx — Installation and Setup

**HH-101 — Caddy binary not found**

HomeHost expected to find Caddy at `~/.homehost/bin/caddy` but it's missing.

```
Fix: Run `homehost setup` to reinstall Caddy automatically.
     Or: homehost install caddy
```

**HH-102 — cloudflared binary not found**

Same as HH-101 but for the cloudflared binary.

```
Fix: Run `homehost setup` or `homehost install cloudflared`.
```

**HH-103 — Caddy checksum mismatch**

The downloaded Caddy binary's SHA-256 hash does not match the expected value. This could indicate a corrupted download or a network MITM.

```
Fix: Delete ~/.homehost/bin/caddy and run `homehost setup` again.
     If it fails repeatedly, check your network/proxy settings.
```

**HH-104 — Python version too old**

HomeHost requires Python 3.10 or higher.

```
Fix: Install Python 3.10+ from https://python.org
     On macOS: brew install python@3.12
     On Windows: Download from python.org and reinstall
```

**HH-105 — Setup wizard interrupted**

The setup wizard exited before completing. The installation may be in an inconsistent state.

```
Fix: Run `homehost setup` again to complete setup.
```

### HH-2xx — Configuration Errors

**HH-201 — Config file invalid (TOML parse error)**

`~/.homehost/config.toml` or `homehost.toml` contains a syntax error.

```
Error: [HH-201] Config parse error in ~/.homehost/config.toml line 14:
       Expected '=' after key

Fix: Open the file in a text editor and fix the TOML syntax.
     Run `homehost config` to open it automatically.
     Or: Delete ~/.homehost/config.toml to reset to defaults.
```

**HH-202 — Unknown project type in config**

`homehost.toml` specifies a `type` that HomeHost doesn't recognize.

```
Fix: Check the list of valid types in docs/quickstart.md.
     Valid values: static, flask, fastapi, django, nextjs, react, express, node
```

**HH-203 — Start command not found**

A custom `start_command` was specified in `homehost.toml`, but the executable doesn't exist or isn't in PATH.

```
Fix: Verify the command works by running it manually in your terminal.
     Check that the required tool (e.g., flask, node) is installed.
```

**HH-204 — Port already in use by another HomeHost project**

You're trying to start a project on a port that another HomeHost project is already using.

```
Fix: Use a different port: homehost serve . --port 8081
     Or stop the conflicting project: homehost list  →  homehost stop <name>
```

### HH-3xx — Server Startup Errors

**HH-301 — Caddy failed to start**

Caddy exited with a non-zero status code immediately after launch. This usually indicates a problem with the generated Caddyfile.

```
Fix: Check the Caddy logs:
     homehost logs <project-name> --caddy

     Common causes:
     - Port 8080 already in use (use --port to change)
     - Invalid characters in the project directory path
     - Caddy binary is corrupted (run: homehost install caddy)
```

**HH-302 — App server health check timeout**

HomeHost started your app server (Flask, Express, etc.) but it did not respond to HTTP requests within 30 seconds.

```
Fix: Start your app manually to see its error output:
     flask run --port 5000  (for Flask)
     node index.js          (for Node)

     Common causes:
     - Missing dependencies (run: pip install -r requirements.txt)
     - Syntax error in your app code
     - App is binding to a different port than expected
       (configure the correct port in homehost.toml)
```

**HH-303 — Port in use (OS-level conflict)**

The port HomeHost wants to use is already bound by another process.

```
Fix: Find what's using the port:
     macOS/Linux: lsof -i :8080
     Windows:     netstat -ano | findstr :8080

     Then either stop that process or use a different port:
     homehost serve . --port 8082
```

**HH-304 — App server crashed on startup**

Your app server started but exited before HomeHost could confirm it was healthy.

```
Fix: Run your app manually to see the full error:
     cd /path/to/project
     flask run   (or your start command)

     Stream HomeHost logs for details:
     homehost logs <project-name>
```

### HH-4xx — Network and Tunnel Errors

**HH-401 — Tunnel failed to connect**

cloudflared started but did not successfully establish a connection to Cloudflare's edge.

```
Fix: Check your internet connection.
     Verify Cloudflare is reachable: curl -I https://cloudflare.com
     Try restarting the tunnel: press 't' twice in the TUI (off, then on)
     Check if your network blocks QUIC (UDP 443):
       - Try on a different network (e.g., mobile hotspot)
       - Some corporate/school networks block QUIC
```

**HH-402 — Tunnel URL not received**

cloudflared connected but did not emit a tunnel URL within 15 seconds.

```
Fix: This is usually transient — try disabling and re-enabling the tunnel.
     If it persists, check cloudflared logs:
     homehost logs <project-name> --cloudflared
```

**HH-403 — Tunnel disconnected unexpectedly**

The cloudflared tunnel dropped after being established. HomeHost will attempt automatic reconnection.

```
Fix: Usually resolves automatically.
     If reconnection fails, toggle the tunnel off and on in the TUI.
     Check for cloudflared updates: homehost update
```

**HH-404 — LAN IP detection failed**

HomeHost could not determine the machine's local network IP address.

```
Fix: This is cosmetic — local serving still works via localhost.
     The "Network: http://x.x.x.x:8080" line won't appear in the TUI.
     Check that you're connected to a network interface.
```

**HH-405 — QUIC/UDP blocked by network**

The Cloudflare Tunnel uses QUIC (UDP port 443). Some networks block UDP traffic.

```
Fix: cloudflared will automatically fall back to HTTP/2 over TCP.
     If both fail, your network is blocking outbound connections to Cloudflare.
     Try on a different network or use a mobile hotspot.
```

### HH-5xx — Runtime Errors

**HH-501 — File watcher failed to start**

The watchdog file watcher could not be initialized for the project directory.

```
Fix: Check that inotify limits aren't exhausted (Linux only, not applicable):
     Verify the project directory exists and is readable.
     Try serving with --no-reload to disable the watcher.
```

**HH-502 — Dashboard failed to start**

The FastAPI web dashboard could not bind to port 9111.

```
Fix: Check if port 9111 is already in use:
     lsof -i :9111  (macOS)
     Change the dashboard port in ~/.homehost/config.toml:
       [dashboard]
       port = 9112
```

**HH-503 — App server restart loop**

Your app server has crashed and restarted more than 5 times in 60 seconds. HomeHost stops retrying to avoid a CPU spin.

```
Fix: The app has a persistent crash. Run it manually to debug:
     cd /path/to/project && flask run

     After fixing the crash, restart with:
     homehost serve .
```

**HH-504 — Log file unwritable**

HomeHost cannot write to its log file at `~/.homehost/logs/homehost.log`.

```
Fix: Check permissions on ~/.homehost/logs/
     ls -la ~/.homehost/logs/
     If missing: mkdir -p ~/.homehost/logs/
```

**HH-505 — Disk space low**

Less than 100 MB of free disk space available. HomeHost may not be able to write logs or download updates.

```
Fix: Free up disk space.
     Rotate old HomeHost logs: rm ~/.homehost/logs/*.log.*
```

---

## Common Issues by Operating System

### macOS

**"homehost: command not found" after pip install**

pip installed HomeHost but the `homehost` script is not in your PATH.

```bash
# Find where pip installs scripts
python3 -m site --user-base
# It's usually ~/Library/Python/3.x/bin

# Add to PATH in ~/.zshrc or ~/.bash_profile:
export PATH="$HOME/Library/Python/3.12/bin:$PATH"

# Reload:
source ~/.zshrc
```

**macOS Gatekeeper blocks Caddy or cloudflared**

macOS may quarantine the downloaded binaries because they're from the internet.

```bash
# Remove the quarantine attribute:
xattr -d com.apple.quarantine ~/.homehost/bin/caddy
xattr -d com.apple.quarantine ~/.homehost/bin/cloudflared

# Or allow them in System Settings > Privacy & Security
```

**Port 5000 already in use on macOS Monterey or later**

macOS 12+ uses port 5000 for AirPlay Receiver.

```bash
# Option 1: Disable AirPlay Receiver
# System Settings > General > AirDrop & Handoff > AirPlay Receiver > Off

# Option 2: Configure Flask to use a different port
# homehost.toml:
[project]
port = 5001
start_command = "flask run --port 5001"
```

**Caddy won't install — disk full**

HomeHost downloads binaries to `~/.homehost/bin/`. If your home directory is on a full volume:

```bash
df -h ~
# Free space on the volume, then retry: homehost setup
```

### Windows

**homehost not found in PowerShell after pip install**

The Python Scripts directory is not in your PATH.

```powershell
# Find the Scripts directory
python -c "import site; print(site.USER_SITE)"
# Replace site-packages with Scripts in that path

# Add to PATH via System Properties > Environment Variables
# Or temporarily:
$env:PATH += ";C:\Users\YourName\AppData\Roaming\Python\Python312\Scripts"
```

**"Access is denied" when starting Caddy on Windows**

Windows Defender Firewall may block Caddy from binding to a port.

```
Fix: When Windows shows a firewall dialog asking to allow Caddy, click "Allow".
     If you dismissed that dialog:
     1. Open Windows Defender Firewall
     2. Click "Allow an app or feature through Windows Defender Firewall"
     3. Add ~/.homehost/bin/caddy.exe
```

**PowerShell execution policy blocks scripts**

```powershell
# Run as Administrator:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**cloudflared QUIC blocked by Windows corporate VPN**

Some corporate VPN clients block UDP traffic. cloudflared should fall back to TCP automatically. If it doesn't:

```
Fix: Temporarily disconnect from VPN to test.
     Contact your IT department about allowing QUIC (UDP 443) outbound.
```

---

## How to Read `homehost doctor` Output

The doctor report has three sections:

**1. Checks** — pass/fail status for each component. All should show `✓`. Any `✗` comes with a suggested fix.

**2. Environment** — your Python version, OS, and HomeHost version. Include this when filing a bug report.

**3. Config summary** — the merged effective config (global + project) that HomeHost is using. Useful for verifying that project overrides are being picked up.

To save the doctor output for a bug report:

```bash
homehost doctor > doctor-report.txt
```

---

## Log File Locations

| Log | Location | Contents |
|---|---|---|
| HomeHost application log | `~/.homehost/logs/homehost.log` | HomeHost internal events (startup, config, errors) |
| Caddy access log | `~/.homehost/logs/caddy-<project>.log` | HTTP request log (method, path, status, latency) |
| Caddy error log | `~/.homehost/logs/caddy-<project>.error.log` | Caddy internal errors |
| cloudflared log | `~/.homehost/logs/cloudflared-<project>.log` | Tunnel connection events |
| App server log | `~/.homehost/logs/app-<project>.log` | Stdout/stderr from your app |

Logs rotate daily and are retained for 7 days by default.

To stream live logs for a project:

```bash
homehost logs <project-name>           # All logs interleaved
homehost logs <project-name> --caddy   # Caddy access log only
homehost logs <project-name> --app     # App server log only
homehost logs <project-name> --tunnel  # cloudflared log only
```

---

## Getting Help

**1. Check this troubleshooting guide** — most common issues are covered here.

**2. Run `homehost doctor`** — it fixes or diagnoses most environment issues automatically.

**3. Search existing GitHub Issues** — [github.com/homehost-dev/homehost/issues](https://github.com/homehost-dev/homehost/issues). Your issue may already be reported and have a fix.

**4. Open a new GitHub Issue** — use the Bug Report template and include:
   - The exact command you ran
   - The full error output (including any traceback)
   - The output of `homehost doctor`
   - Your OS and Python version

---

## Resetting HomeHost (Nuclear Option)

If HomeHost is in a broken state and nothing else works, you can reset it completely:

```bash
# Stop all running projects first
homehost stop --all

# Delete the HomeHost data directory
# WARNING: This deletes your config, installed binaries, and logs
rm -rf ~/.homehost          # macOS/Linux
rmdir /s /q %USERPROFILE%\.homehost   # Windows

# Reinstall
pip install --force-reinstall homehost
homehost setup
```

This is a last resort. You'll lose your global config (`~/.homehost/config.toml`), installed binaries (Caddy, cloudflared — they'll be re-downloaded), and log history. Your project files and `homehost.toml` project configs are not affected since they live in your project directories.
