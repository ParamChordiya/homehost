"""Caddy security configuration generators and project security posture checks."""

from __future__ import annotations

import re
from pathlib import Path

# ── Security headers ───────────────────────────────────────────────────────────

SECURITY_HEADERS: dict[str, str] = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

# ── Caddy block generators ─────────────────────────────────────────────────────


def generate_security_headers_caddy_block() -> str:
    """Return a Caddy 'header' block with all security headers.

    Produces a Caddyfile-compatible ``header`` directive that sets every
    entry from :data:`SECURITY_HEADERS` and removes the ``Server`` header
    to avoid fingerprinting.
    """
    lines: list[str] = ["header {"]
    # Remove server fingerprint header
    lines.append("    # Remove server fingerprint")
    lines.append("    -Server")
    lines.append("    -X-Powered-By")
    lines.append("")
    lines.append("    # Security headers")
    for name, value in SECURITY_HEADERS.items():
        # Caddy requires values with spaces to be quoted
        safe_value = f'"{value}"' if " " in value or ";" in value else value
        lines.append(f"    {name} {safe_value}")
    lines.append("}")
    return "\n".join(lines)


def generate_rate_limit_block(requests_per_minute: int = 100) -> str:
    """Return a Caddy rate_limit configuration block.

    .. note::
        This block requires the ``caddy-ratelimit`` third-party plugin
        (https://github.com/mholt/caddy-ratelimit).  It will be silently
        ignored by a stock Caddy build.  Install via::

            xcaddy build --with github.com/mholt/caddy-ratelimit

    Args:
        requests_per_minute: Maximum requests allowed per minute per client IP.

    Returns:
        A Caddyfile ``rate_limit`` block string.
    """
    # Convert rpm to a per-second window for the plugin syntax
    window_seconds = 60
    lines: list[str] = [
        "# rate_limit requires the caddy-ratelimit plugin:",
        "# xcaddy build --with github.com/mholt/caddy-ratelimit",
        "rate_limit {",
        "    zone dynamic {",
        "        key        {remote_host}",
        f"        events     {requests_per_minute}",
        f"        window     {window_seconds}s",
        "    }",
        "}",
    ]
    return "\n".join(lines)


def generate_dotfile_block() -> str:
    """Return Caddy config to block access to dotfiles and sensitive paths.

    Blocks requests to paths starting with ``.`` (e.g. ``.env``, ``.git``),
    responding with ``403 Forbidden``.
    """
    lines: list[str] = [
        "# Block dotfiles and sensitive directories",
        "@dotfiles {",
        "    path_regexp dotfiles ^/\\..*",
        "}",
        "respond @dotfiles 403",
        "",
        "# Block common sensitive paths regardless of leading dot",
        "@sensitive_paths {",
        "    path /.env /.env.* /.git/* /.github/* /.htaccess /.htpasswd",
        "    path /wp-config.php /web.config /server.key /id_rsa",
        "}",
        "respond @sensitive_paths 403",
    ]
    return "\n".join(lines)


def generate_full_security_block(
    rate_limit: int = 100,
    basic_auth: bool = False,
    username: str = "",
    password_hash: str = "",
) -> str:
    """Return combined Caddy security configuration block.

    Assembles headers, dotfile protection, optional rate limiting, and
    optional HTTP basic authentication into a single ready-to-embed block.

    Args:
        rate_limit: Requests per minute per IP (0 disables rate limiting).
        basic_auth: Whether to emit a ``basicauth`` block.
        username: Username for basic auth (required when basic_auth=True).
        password_hash: Bcrypt hash of the password (required when basic_auth=True).

    Returns:
        A multi-line Caddyfile configuration string.
    """
    sections: list[str] = []

    # 1. Security headers
    sections.append("# ── Security Headers ──────────────────────────────────────────")
    sections.append(generate_security_headers_caddy_block())

    # 2. Dotfile / sensitive path protection
    sections.append("")
    sections.append("# ── Path Protection ───────────────────────────────────────────")
    sections.append(generate_dotfile_block())

    # 3. Rate limiting (optional)
    if rate_limit > 0:
        sections.append("")
        sections.append("# ── Rate Limiting ─────────────────────────────────────────────")
        sections.append(generate_rate_limit_block(rate_limit))

    # 4. Basic auth (optional)
    if basic_auth and username and password_hash:
        sections.append("")
        sections.append("# ── Basic Authentication ──────────────────────────────────────")
        sections.append(_generate_basicauth_block(username, password_hash))

    return "\n".join(sections)


def _generate_basicauth_block(username: str, password_hash: str) -> str:
    """Internal helper — emit a Caddy basicauth block."""
    return "\n".join(
        [
            "basicauth /* {",
            f"    {username} {password_hash}",
            "}",
        ]
    )


# ── Security posture checker ───────────────────────────────────────────────────

# Patterns indicating hard-coded credentials in source files
_CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?i)(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']'),
    re.compile(r'(?i)(api_key|apikey|api_secret|secret_key)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'(?i)(token|auth_token|access_token)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'(?i)(aws_access_key_id|aws_secret_access_key)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r"(?i)-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]

# Known vulnerable package names (informational — not exhaustive)
_KNOWN_VULNERABLE: set[str] = {
    "pyyaml",  # various RCE issues in older versions
    "pillow",  # image parsing vulns in older versions
    "cryptography",  # regularly patched; flag for review
    "paramiko",  # SSH library; old versions have issues
    "requests",  # older versions had redirect-bypass issues
    "urllib3",  # older versions lacked TLS validation
    "django",  # pinned old versions regularly have CVEs
    "flask",
    "jinja2",
    "setuptools",
    "pip",
    "werkzeug",
    "aiohttp",
}

# Common external CDN hostnames
_CDN_HOSTS: list[str] = [
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
    "stackpath.bootstrapcdn.com",
    "maxcdn.bootstrapcdn.com",
    "code.jquery.com",
    "ajax.googleapis.com",
    "fonts.googleapis.com",
    "use.fontawesome.com",
]


def check_security_posture(project_path: str, project_type: str) -> list[dict[str, str]]:
    """Check a project's security posture.

    Performs lightweight static analysis of the project directory and returns
    a list of security findings sorted by severity (high → info).

    Args:
        project_path: Absolute path to the project root directory.
        project_type: One of the :class:`~homehost.core.project.ProjectType` values
            (e.g. ``"static"``, ``"flask"``).

    Returns:
        List of finding dicts, each containing:

        - ``severity``: ``"high"`` | ``"medium"`` | ``"low"`` | ``"info"``
        - ``title``: Short summary.
        - ``description``: Detailed explanation.
        - ``fix``: Remediation advice.
    """
    findings: list[dict[str, str]] = []
    root = Path(project_path)

    if not root.is_dir():
        return [
            {
                "severity": "info",
                "title": "Project directory not found",
                "description": f"Path '{project_path}' does not exist or is not a directory.",
                "fix": "Ensure the project path is correctly configured.",
            }
        ]

    # ── Check 1: .env file present ────────────────────────────────────────────
    env_files = [root / ".env"] + list(root.glob(".env.*"))
    exposed_env = [f for f in env_files if f.is_file()]
    if exposed_env:
        names = ", ".join(f.name for f in exposed_env)
        findings.append(
            {
                "severity": "high",
                "title": "Environment file(s) may be served publicly",
                "description": (
                    f"Found {names} in the project root. If Caddy serves this directory, "
                    "these files — which often contain secrets — could be downloaded by anyone."
                ),
                "fix": (
                    "Move secrets out of the web root, use the HomeHost secret store, "
                    "and ensure dotfile blocking is enabled in the Caddyfile."
                ),
            }
        )

    # ── Check 2: .git directory accessible ───────────────────────────────────
    git_dir = root / ".git"
    if git_dir.is_dir():
        findings.append(
            {
                "severity": "medium",
                "title": ".git directory is inside web root",
                "description": (
                    "The .git directory is present inside the served directory. "
                    "Exposing it allows attackers to reconstruct your entire source code."
                ),
                "fix": (
                    "Serve from a build/dist subdirectory rather than the repository root, "
                    "or ensure the dotfile-blocking rule is active in your Caddyfile."
                ),
            }
        )

    # ── Check 3: requirements.txt mentions known sensitive packages ───────────
    req_file = root / "requirements.txt"
    if req_file.is_file():
        try:
            req_text = req_file.read_text(encoding="utf-8", errors="ignore")
            mentioned = []
            for line in req_text.splitlines():
                name = re.split(r"[>=<!~\[\s]", line.strip().lower())[0]
                if name in _KNOWN_VULNERABLE and "==" not in line:
                    mentioned.append(name)
            if mentioned:
                findings.append(
                    {
                        "severity": "low",
                        "title": "Unpinned sensitive dependencies in requirements.txt",
                        "description": (
                            f"The following packages are not pinned to an exact version and have "
                            f"historical CVEs: {', '.join(mentioned)}. "
                            "Without pinning, pip may install a vulnerable release."
                        ),
                        "fix": (
                            "Pin all dependencies to exact versions (e.g. flask==3.0.3) and "
                            "run 'pip-audit' or 'safety check' regularly."
                        ),
                    }
                )
        except OSError:
            pass

    # ── Check 4: index.html references external CDN ───────────────────────────
    index_html = root / "index.html"
    if index_html.is_file():
        try:
            html_text = index_html.read_text(encoding="utf-8", errors="ignore")
            cdn_hits = [h for h in _CDN_HOSTS if h in html_text]
            if cdn_hits:
                findings.append(
                    {
                        "severity": "low",
                        "title": "External CDN resources detected in index.html",
                        "description": (
                            f"index.html loads resources from: {', '.join(cdn_hits)}. "
                            "This creates a supply-chain dependency on third-party infrastructure "
                            "and may violate a strict Content-Security-Policy."
                        ),
                        "fix": (
                            "Self-host all JS/CSS assets, or use Subresource Integrity (SRI) "
                            "attributes and update the CSP to allow the specific CDN origins."
                        ),
                    }
                )
        except OSError:
            pass

    # ── Check 5: No HTTPS / public-access concern ─────────────────────────────
    # This is a heuristic — we flag it as informational since we can't know
    # the full deployment context from files alone.
    if project_type in ("flask", "fastapi", "django", "node", "nextjs", "react"):
        findings.append(
            {
                "severity": "medium",
                "title": "Verify HTTPS is enforced for public access",
                "description": (
                    f"Project type '{project_type}' typically handles authenticated sessions or "
                    "API calls. If this project is publicly accessible, all traffic must go over "
                    "HTTPS to protect credentials and data in transit."
                ),
                "fix": (
                    "Enable the Cloudflare Tunnel option in HomeHost (which terminates TLS at "
                    "Cloudflare's edge), or configure a custom domain with Let's Encrypt via Caddy."
                ),
            }
        )

    # ── Check 6: Hard-coded credentials in source files ───────────────────────
    credential_hits: list[str] = []
    py_files = list(root.glob("**/*.py"))[:50]  # cap to avoid runaway scans
    js_files = list(root.glob("**/*.js"))[:30]
    env_example = list(root.glob(".env.example"))
    scan_files = py_files + js_files + env_example

    for src_file in scan_files:
        # Skip virtual-env and node_modules trees
        if any(part in src_file.parts for part in ("node_modules", ".venv", "venv", "__pycache__")):
            continue
        try:
            text = src_file.read_text(encoding="utf-8", errors="ignore")
            for pattern in _CREDENTIAL_PATTERNS:
                match = pattern.search(text)
                if match:
                    relative = src_file.relative_to(root)
                    credential_hits.append(str(relative))
                    break  # one finding per file is enough
        except OSError:
            continue

    if credential_hits:
        files_str = ", ".join(credential_hits[:5])
        if len(credential_hits) > 5:
            files_str += f" (and {len(credential_hits) - 5} more)"
        findings.append(
            {
                "severity": "high",
                "title": "Possible hard-coded credentials detected",
                "description": (
                    f"Credential-like patterns were found in: {files_str}. "
                    "Hard-coded secrets in source files are easily leaked via version control."
                ),
                "fix": (
                    "Move all secrets to environment variables or the HomeHost secret store. "
                    "Use python-decouple or dotenv to read them at runtime."
                ),
            }
        )

    # Sort: high → medium → low → info
    _order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings.sort(key=lambda f: _order.get(f["severity"], 4))
    return findings
