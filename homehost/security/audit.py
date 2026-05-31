"""Security audit engine — scans projects and Caddy configs for vulnerabilities."""

from __future__ import annotations

import re
import socket
import stat
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class AuditFinding:
    """A single security finding produced by the audit engine.

    Attributes:
        severity: One of ``"critical"``, ``"high"``, ``"medium"``, ``"low"``, ``"info"``.
        code: Unique finding code (e.g. ``"HH-SEC-001"``).
        title: Short summary of the finding.
        description: Detailed explanation of the risk.
        fix: Actionable remediation advice.
        project_name: Name of the project this finding belongs to, or ``""``
            for host-level findings.
    """

    severity: str
    code: str
    title: str
    description: str
    fix: str
    project_name: str = ""


# Severity → numeric weight for risk scoring
_SEVERITY_WEIGHT: dict[str, int] = {
    "critical": 40,
    "high": 20,
    "medium": 10,
    "low": 3,
    "info": 0,
}

_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

# Ports that are expected to be open on a developer machine running HomeHost
_EXPECTED_PORTS: set[int] = {
    22,    # SSH
    53,    # DNS
    80,    # HTTP (Caddy)
    443,   # HTTPS (Caddy)
    8080,  # Default HomeHost project port
    9111,  # HomeHost dashboard
}

# Ports that are high-risk if open to the network
_HIGH_RISK_PORTS: dict[int, str] = {
    21:    "FTP — plaintext file transfer",
    23:    "Telnet — plaintext remote access",
    25:    "SMTP — mail relay (potential spam source)",
    110:   "POP3 — plaintext mail",
    143:   "IMAP — plaintext mail",
    445:   "SMB — Windows file sharing (ransomware target)",
    3306:  "MySQL — database exposed to network",
    5432:  "PostgreSQL — database exposed to network",
    5900:  "VNC — remote desktop",
    6379:  "Redis — in-memory store (unauthenticated by default)",
    27017: "MongoDB — document store (unauthenticated by default)",
}

# Patterns indicating hard-coded secrets in source files
_CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?i)(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']'),
    re.compile(r'(?i)(api_key|apikey|api_secret|secret_key)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'(?i)(token|auth_token|access_token)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'(?i)(aws_access_key_id|aws_secret_access_key)\s*=\s*["\'][^"\']{8,}["\']'),
    re.compile(r'(?i)-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'(?i)(database_url|db_url)\s*=\s*["\'][^"\']{10,}["\']'),
]

# Caddy config patterns we check for
_CADDY_SECURITY_HEADER_PATTERN = re.compile(r'Strict-Transport-Security|X-Content-Type-Options')
_CADDY_RATE_LIMIT_PATTERN = re.compile(r'rate_limit\s*\{')
_CADDY_BASICAUTH_PATTERN = re.compile(r'basicauth\s+')
_CADDY_DOTFILE_PATTERN = re.compile(r'path_regexp.*dotfiles|respond.*403')


class SecurityAuditor:
    """Runs comprehensive security audits across HomeHost projects and host config.

    The auditor gathers findings from multiple sources:

    - Host-level: open port scan.
    - Per-project: file system analysis (credentials, world-writable paths, .env).
    - Caddy config: presence of headers, rate limiting, etc.

    Usage::

        auditor = SecurityAuditor()
        findings = auditor.run_full_audit(project_configs)
        report = auditor.generate_report(findings)
        score, rating = auditor.get_risk_score(findings)
    """

    # ── Full audit ─────────────────────────────────────────────────────────────

    def run_full_audit(self, project_configs: list[Any]) -> list[AuditFinding]:
        """Run all security checks across all projects.

        Args:
            project_configs: A list of :class:`~homehost.core.config.ProjectConfig`
                objects (or any objects with ``.name``, ``.path``, and
                ``.server`` attributes).  Pass an empty list to audit host-only.

        Returns:
            A list of :class:`AuditFinding` objects sorted by severity.
        """
        findings: list[AuditFinding] = []

        # Host-level checks
        findings.extend(self.check_open_ports())

        for cfg in project_configs:
            name = getattr(cfg, "name", str(cfg))
            path = getattr(cfg, "path", "")

            # Per-project file checks
            findings.extend(self.check_project_files(path, name))

            # Check associated Caddyfile if we can locate it
            from homehost.core.config import homehost_dir
            caddy_path = homehost_dir() / "projects" / name / "Caddyfile"
            if caddy_path.is_file():
                findings.extend(self.check_caddy_config(str(caddy_path)))

            # Check whether basic auth is enabled
            security_cfg = getattr(cfg, "security", None)
            if security_cfg is not None and not getattr(security_cfg, "basic_auth", False):
                findings.append(
                    AuditFinding(
                        severity="info",
                        code="HH-SEC-005",
                        title="Basic auth not enabled",
                        description=(
                            f"Project '{name}' is accessible without authentication. "
                            "Anyone who can reach the URL can view or interact with it."
                        ),
                        fix=(
                            "Run 'homehost auth enable <project>' to add HTTP basic "
                            "authentication, especially if the project is publicly tunnelled."
                        ),
                        project_name=name,
                    )
                )

        findings.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))
        return findings

    # ── Host-level checks ──────────────────────────────────────────────────────

    def check_open_ports(self) -> list[AuditFinding]:
        """Check for unexpected open ports on the local machine.

        Scans a targeted list of well-known high-risk ports (non-privileged
        scan — connects to 127.0.0.1) rather than a full port sweep to keep
        the audit fast and avoid false positives.

        Returns:
            Findings for each high-risk port that is open and listening.
        """
        findings: list[AuditFinding] = []
        open_ports: list[int] = []

        scan_targets = list(_HIGH_RISK_PORTS.keys()) + [
            p for p in range(8000, 8100) if p not in _EXPECTED_PORTS
        ]

        for port in sorted(set(scan_targets)):
            if _is_port_open("127.0.0.1", port, timeout=0.3):
                open_ports.append(port)

        for port in open_ports:
            if port in _HIGH_RISK_PORTS:
                description = _HIGH_RISK_PORTS[port]
                findings.append(
                    AuditFinding(
                        severity="high",
                        code="HH-SEC-008",
                        title=f"High-risk port {port} is open ({description.split('—')[0].strip()})",
                        description=(
                            f"Port {port} ({description}) is open and listening on localhost. "
                            "If your Cloudflare Tunnel or router port-forwarding exposes this "
                            "port, it may be reachable from the internet."
                        ),
                        fix=(
                            f"If you do not need this service, stop it. "
                            f"If it must run, bind it to 127.0.0.1 only and ensure it is "
                            f"not included in any port-forwarding or tunnel rules."
                        ),
                        project_name="",
                    )
                )
            else:
                # Unexpected port in the 8000-8099 range
                if port not in _EXPECTED_PORTS:
                    findings.append(
                        AuditFinding(
                            severity="low",
                            code="HH-SEC-009",
                            title=f"Unregistered HomeHost port {port} is open",
                            description=(
                                f"Port {port} is open but not registered as an active HomeHost "
                                "project. An unknown process may be listening on it."
                            ),
                            fix=(
                                "Run 'lsof -i :{port}' to identify the process and shut it "
                                "down if it's not intentional."
                            ),
                            project_name="",
                        )
                    )

        return findings

    # ── Project file checks ────────────────────────────────────────────────────

    def check_project_files(self, project_path: str, project_name: str) -> list[AuditFinding]:
        """Check project files for common security issues.

        Inspects the project root for:

        - ``.env`` files that could expose secrets.
        - Source files with hard-coded credential patterns.
        - World-writable directories that could allow privilege escalation.

        Args:
            project_path: Absolute path to the project root.
            project_name: Display name for findings.

        Returns:
            A list of :class:`AuditFinding` objects.
        """
        findings: list[AuditFinding] = []
        root = Path(project_path)

        if not root.is_dir():
            return findings

        # ── HH-SEC-001: .env file present ─────────────────────────────────────
        env_files = [root / ".env"] + list(root.glob(".env.*"))
        exposed_env = [f for f in env_files if f.is_file() and f.name != ".env.example"]
        if exposed_env:
            names = ", ".join(f.name for f in exposed_env)
            findings.append(
                AuditFinding(
                    severity="high",
                    code="HH-SEC-001",
                    title=".env file(s) found in project root",
                    description=(
                        f"Found {names} in '{project_name}'. If Caddy serves this directory "
                        "directly, these files — which typically contain API keys, database "
                        "credentials, and other secrets — may be downloadable by anyone."
                    ),
                    fix=(
                        "Ensure dotfile blocking is enabled in your Caddyfile (HomeHost enables "
                        "this by default). Consider storing secrets in the HomeHost secret store "
                        "instead ('homehost secrets set <key> <value>')."
                    ),
                    project_name=project_name,
                )
            )

        # ── HH-SEC-006: Hard-coded credentials ────────────────────────────────
        credential_hits: list[tuple[str, str]] = []  # (relative_path, matched_text)

        source_globs = ["**/*.py", "**/*.js", "**/*.ts", "**/*.env", "**/*.cfg", "**/*.ini"]
        scanned: list[Path] = []
        for glob in source_globs:
            scanned.extend(root.glob(glob))
            if len(scanned) > 200:
                break

        for src_file in scanned[:200]:
            # Skip build/dependency trees
            skip_parts = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build"}
            if any(part in skip_parts for part in src_file.parts):
                continue
            try:
                text = src_file.read_text(encoding="utf-8", errors="ignore")
                for pattern in _CREDENTIAL_PATTERNS:
                    m = pattern.search(text)
                    if m:
                        relative = src_file.relative_to(root)
                        credential_hits.append((str(relative), m.group(0)[:60]))
                        break  # one hit per file
            except OSError:
                continue

        if credential_hits:
            file_list = ", ".join(h[0] for h in credential_hits[:5])
            if len(credential_hits) > 5:
                file_list += f" (+{len(credential_hits) - 5} more)"
            findings.append(
                AuditFinding(
                    severity="high",
                    code="HH-SEC-006",
                    title="Possible hard-coded credentials detected",
                    description=(
                        f"Credential-like patterns were found in {len(credential_hits)} file(s): "
                        f"{file_list}. Hard-coded secrets are easily leaked via version control "
                        "repositories or log files."
                    ),
                    fix=(
                        "Move secrets to environment variables loaded from .env at runtime, "
                        "or use 'homehost secrets set <key>' to store them securely. "
                        "Add .env to .gitignore and rotate any exposed credentials immediately."
                    ),
                    project_name=project_name,
                )
            )

        # ── World-writable directories ─────────────────────────────────────────
        world_writable: list[str] = []
        try:
            for item in root.iterdir():
                if item.is_dir():
                    mode = item.stat().st_mode
                    if mode & stat.S_IWOTH:  # world-writable bit
                        world_writable.append(item.name)
        except OSError:
            pass

        if world_writable:
            dirs = ", ".join(world_writable[:5])
            findings.append(
                AuditFinding(
                    severity="medium",
                    code="HH-SEC-010",
                    title="World-writable directories found in project",
                    description=(
                        f"The following directories are world-writable in '{project_name}': {dirs}. "
                        "This allows any local user or process to modify their contents."
                    ),
                    fix=(
                        "Run 'chmod o-w <dir>' on each affected directory. "
                        "Directories should typically be mode 0755 and files 0644."
                    ),
                    project_name=project_name,
                )
            )

        return findings

    # ── Caddy config checks ────────────────────────────────────────────────────

    def check_caddy_config(self, caddyfile_path: str) -> list[AuditFinding]:
        """Verify a Caddyfile contains required security directives.

        Checks for:

        - Security headers (``HH-SEC-004``).
        - Rate limiting (``HH-SEC-003``).
        - Whether basic auth appears configured (``HH-SEC-005`` info).

        Args:
            caddyfile_path: Absolute path to the Caddyfile to inspect.

        Returns:
            A list of :class:`AuditFinding` objects.
        """
        findings: list[AuditFinding] = []
        path = Path(caddyfile_path)

        if not path.is_file():
            return findings

        # Determine project name from parent directory
        project_name = path.parent.name

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return findings

        # ── HH-SEC-004: Security headers ──────────────────────────────────────
        if not _CADDY_SECURITY_HEADER_PATTERN.search(content):
            findings.append(
                AuditFinding(
                    severity="medium",
                    code="HH-SEC-004",
                    title="Security headers missing from Caddyfile",
                    description=(
                        f"The Caddyfile for '{project_name}' does not appear to include "
                        "security headers such as Strict-Transport-Security or "
                        "X-Content-Type-Options. Without these headers, browsers may be "
                        "vulnerable to XSS, clickjacking, and MIME-sniffing attacks."
                    ),
                    fix=(
                        "Re-generate the Caddyfile via 'homehost config apply <project>' — "
                        "HomeHost includes security headers by default. "
                        "Alternatively, add a 'header { ... }' block manually."
                    ),
                    project_name=project_name,
                )
            )

        # ── HH-SEC-003: Rate limiting ──────────────────────────────────────────
        if not _CADDY_RATE_LIMIT_PATTERN.search(content):
            findings.append(
                AuditFinding(
                    severity="medium",
                    code="HH-SEC-003",
                    title="Rate limiting not configured in Caddyfile",
                    description=(
                        f"The Caddyfile for '{project_name}' does not have a rate_limit block. "
                        "Without rate limiting, a single IP can flood the server with requests, "
                        "causing denial of service or brute-forcing login forms."
                    ),
                    fix=(
                        "Install the caddy-ratelimit plugin and add a rate_limit block, "
                        "or re-generate the Caddyfile via 'homehost config apply <project>'."
                    ),
                    project_name=project_name,
                )
            )

        # ── HH-SEC-002: .git directory accessible ─────────────────────────────
        if not _CADDY_DOTFILE_PATTERN.search(content):
            findings.append(
                AuditFinding(
                    severity="medium",
                    code="HH-SEC-002",
                    title=".git directory may be accessible via web",
                    description=(
                        f"The Caddyfile for '{project_name}' does not appear to block dotfile "
                        "paths (e.g. /.git/, /.env). Attackers can use tools like git-dumper to "
                        "reconstruct source code from an exposed .git directory."
                    ),
                    fix=(
                        "Add a dotfile-blocking block to the Caddyfile, or re-generate it via "
                        "'homehost config apply <project>'. HomeHost includes dotfile blocking by default."
                    ),
                    project_name=project_name,
                )
            )

        return findings

    # ── Report generation ──────────────────────────────────────────────────────

    def generate_report(self, findings: list[AuditFinding]) -> str:
        """Generate a human-readable audit report string.

        The report is formatted as plain text suitable for printing to a
        terminal (not Rich markup) so it can also be written to a file.

        Args:
            findings: The findings list returned by :meth:`run_full_audit`.

        Returns:
            A multi-line report string.
        """
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        score, rating = self.get_risk_score(findings)

        counts: dict[str, int] = {s: 0 for s in ("critical", "high", "medium", "low", "info")}
        for f in findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1

        lines: list[str] = [
            "=" * 70,
            "  HomeHost Security Audit Report",
            f"  Generated : {now}",
            "=" * 70,
            "",
            f"  Risk Score : {score}/100  ({rating})",
            "",
            "  Findings Summary",
            "  ----------------",
        ]
        for severity in ("critical", "high", "medium", "low", "info"):
            count = counts[severity]
            if count:
                lines.append(f"    {severity.upper():<10} {count}")

        if not findings:
            lines.append("    No issues found — looking good!")

        lines.append("")
        lines.append("  Detailed Findings")
        lines.append("  -----------------")

        if not findings:
            lines.append("  (none)")
        else:
            sorted_findings = sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))
            for i, finding in enumerate(sorted_findings, start=1):
                sev = finding.severity.upper()
                proj = f" [{finding.project_name}]" if finding.project_name else ""
                lines.append("")
                lines.append(f"  [{i}] [{sev}] {finding.code}{proj} — {finding.title}")
                lines.append(f"      {finding.description}")
                lines.append(f"      FIX: {finding.fix}")

        lines.append("")
        lines.append("=" * 70)
        lines.append(
            "  Run 'homehost audit --fix' to auto-remediate where possible."
        )
        lines.append("=" * 70)
        return "\n".join(lines)

    # ── Risk scoring ───────────────────────────────────────────────────────────

    def get_risk_score(self, findings: list[AuditFinding]) -> tuple[int, str]:
        """Return a (score, rating) tuple based on findings severity.

        The score starts at 100 and points are deducted for each finding
        according to its severity weight.  The score is clamped to [0, 100].

        Score thresholds:

        - 90–100 : Excellent
        - 75–89  : Good
        - 50–74  : Fair
        - 25–49  : Poor
        - 0–24   : Critical

        Args:
            findings: The list of :class:`AuditFinding` objects to score.

        Returns:
            A ``(int, str)`` tuple of ``(score, rating)``.
        """
        deduction = sum(_SEVERITY_WEIGHT.get(f.severity, 0) for f in findings)
        score = max(0, min(100, 100 - deduction))

        if score >= 90:
            rating = "Excellent"
        elif score >= 75:
            rating = "Good"
        elif score >= 50:
            rating = "Fair"
        elif score >= 25:
            rating = "Poor"
        else:
            rating = "Critical"

        return score, rating


# ── Helpers ────────────────────────────────────────────────────────────────────


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """Return True if *port* on *host* accepts a TCP connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ConnectionRefusedError, TimeoutError):
        return False
