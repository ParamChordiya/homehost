# Security Guide

HomeHost is designed to make secure hosting the default, not an afterthought. This document explains what HomeHost configures automatically, what the threat model covers, and what you must handle yourself for production workloads.

---

## What HomeHost Configures Automatically

### Security Headers

Every response served through HomeHost's Caddy instance includes the following HTTP security headers. These are injected automatically — you don't need to configure them in your app.

| Header | Value | Purpose |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'` | Prevents XSS by blocking inline scripts and external resources by default |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS for one year (via Cloudflare Tunnel) |
| `X-Frame-Options` | `DENY` | Prevents your site from being embedded in iframes (clickjacking protection) |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing attacks |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer information sent to third parties |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Disables browser APIs your site likely doesn't need |

**Relaxing headers for your project:**

If your app legitimately needs to embed external content or use browser APIs, you can customize headers in `homehost.toml`:

```toml
[security]
# Allow inline scripts (needed for some analytics tools — use with care)
csp = "default-src 'self'; script-src 'self' 'unsafe-inline' https://analytics.example.com"

# Allow your site to be embedded (not recommended)
x_frame_options = "SAMEORIGIN"
```

### Rate Limiting

By default, Caddy limits each client IP to **300 requests per minute**. Clients that exceed this limit receive a `429 Too Many Requests` response. This prevents simple brute-force and scraping attacks.

Change the limit globally in `~/.homehost/config.toml`:

```toml
[security]
rate_limit_rpm = 600   # Higher limit for high-traffic demos
```

Or per-project in `homehost.toml`:

```toml
[security]
rate_limit_rpm = 100   # Stricter limit for an API
```

To disable rate limiting entirely (not recommended):

```toml
[security]
rate_limit_rpm = 0   # Disabled
```

### No Direct IP Exposure

When you use the Cloudflare Tunnel (`--public`), your machine's public IP address is never revealed to visitors. All traffic flows through Cloudflare's edge network. A visitor who runs `nslookup proud-tiger-42.trycloudflare.com` will see Cloudflare's IP addresses, not yours.

Without the tunnel (local-only mode), your site is accessible only on your local network. It is not reachable from the internet.

### HTTPS

The Cloudflare Tunnel provides end-to-end HTTPS automatically:

- Traffic between the browser and Cloudflare's edge is encrypted with TLS (certificate managed by Cloudflare)
- Traffic between Cloudflare's edge and your machine travels through cloudflared's encrypted QUIC tunnel
- Traffic between cloudflared and Caddy is on localhost (no network hop)

You do not need to manage certificates, run Let's Encrypt, or open port 443.

---

## Threat Model

### What HomeHost protects against

**Casual attackers and bots**
- Security headers defend against common web vulnerabilities: XSS, clickjacking, MIME sniffing
- Rate limiting prevents brute-force login attempts and simple scraping
- No open ports means port scanners won't find your service

**IP-based targeting**
- The Cloudflare Tunnel hides your home IP. Even if someone knows your trycloudflare.com URL, they cannot trivially find your home address

**Basic credential theft**
- bcrypt hashing means stored Basic Auth passwords are not recoverable even if `~/.homehost/` is compromised

**Accidental public exposure of the web dashboard**
- The dashboard (`localhost:9111`) is bound to `127.0.0.1` only. It is not routed through the Cloudflare Tunnel. It is not accessible from the internet or your LAN.

### What HomeHost does NOT protect against

**Vulnerabilities in your application code**
- HomeHost secures the transport layer and adds defensive headers. It cannot protect against SQL injection, insecure deserialization, broken access control, or other application-level vulnerabilities in your code. You are responsible for the security of your application.

**Determined, targeted attackers**
- HomeHost is designed for demos, development, and personal projects — not for protecting high-value targets. A sophisticated attacker with sufficient motivation may be able to correlate traffic patterns, exploit zero-days in Caddy or cloudflared, or attack your application directly.

**Data-in-transit between Cloudflare and your machine (for high-sensitivity data)**
- Cloudflare terminates TLS at their edge. If you are handling very sensitive data (medical records, financial data, etc.), you should be aware that Cloudflare decrypts and re-encrypts traffic at their edge. This is a property of any CDN/tunnel service.

**DDoS at scale**
- The Cloudflare free tier provides basic DDoS mitigation, but a sustained high-volume attack could exhaust rate limits or overwhelm your machine's resources. HomeHost is not designed for production-grade DDoS resilience.

---

## Production Workloads

HomeHost is designed for personal use, local development, demos, and hosting side projects. It is **not recommended** for:

- Applications handling payment card data (PCI DSS requirements)
- Applications handling protected health information (HIPAA requirements)
- Applications serving millions of users
- Applications where uptime guarantees are required

For production workloads, consider deploying to a cloud provider or dedicated server, and use Cloudflare's full-featured tunnel product (not the free `trycloudflare.com` quick tunnel) with a named tunnel and your own domain.

---

## How to Enable Basic Auth

Basic Auth adds username/password protection to your site. Browsers will show a login dialog before serving any content.

### Enable at startup

```bash
homehost serve . --auth
# Enter username: admin
# Enter password: (hidden — minimum 8 characters)
# Confirm password: (hidden)
# Basic auth enabled for project "my-app"
```

### Enable in project config

```toml
# homehost.toml
[auth]
enabled = true
username = "admin"
# Password is stored as a bcrypt hash in ~/.homehost/auth/my-app.toml
# Set it with: homehost auth set-password my-app
```

### What Basic Auth protects

Basic Auth restricts access to the Caddy-served URLs:
- `http://localhost:8080` — protected
- `https://proud-tiger-42.trycloudflare.com` — protected

It does not protect the web dashboard (`localhost:9111`) — the dashboard is localhost-only and not publicly accessible.

### Limitations of Basic Auth

- Basic Auth transmits credentials as base64 (not encrypted) over HTTP. Over the Cloudflare Tunnel (HTTPS), this is safe. On your local `http://localhost` URL, do not share the password over the local network with untrusted parties.
- Basic Auth is not a substitute for application-level authentication. If your app has user accounts, implement proper session management within the app.

---

## How to Rotate Credentials

To change the Basic Auth password for a project:

```bash
homehost auth set-password <project-name>
# Enter new password: (hidden)
# Confirm new password: (hidden)
# Password updated. Caddy will reload automatically.
```

The old password hash is overwritten in `~/.homehost/auth/<project-name>.toml` and Caddy is sent a reload signal. There is no downtime.

To remove Basic Auth entirely:

```bash
homehost auth disable <project-name>
# Basic auth disabled for "my-app". Caddy reloaded.
```

Or set `enabled = false` in `homehost.toml` and run `homehost serve` again.

---

## Security Reporting

If you discover a security vulnerability in HomeHost, please report it responsibly:

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, email the maintainers at: **security@homehost.dev**

Include:
- A description of the vulnerability
- Steps to reproduce
- The potential impact
- Any suggested mitigations (optional)

You will receive an acknowledgment within 48 hours. We aim to triage and publish a fix within 14 days for critical issues. Once a fix is released, you will be credited in the changelog unless you prefer to remain anonymous.

We do not currently have a formal bug bounty program, but we deeply appreciate responsible disclosure.

---

## Hardening Checklist

For projects where security matters, review this checklist before sharing a HomeHost URL:

- [ ] Always use the Cloudflare Tunnel (`--public`) — never open your home router's firewall to the internet
- [ ] Enable Basic Auth for any project that shouldn't be publicly accessible
- [ ] Review and tighten your Content Security Policy if your app loads external resources
- [ ] Make sure your `.env` file is in `.gitignore` and not committed to your repo
- [ ] Do not store secrets (API keys, passwords) in files served by the static file server
- [ ] Rotate your Basic Auth password if you've shared it and it may have been compromised
- [ ] Review `homehost doctor` output — it flags common security misconfigurations
