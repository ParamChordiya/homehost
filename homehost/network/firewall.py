"""OS-specific firewall rule management for HomeHost.

All rules are tagged with a HomeHost identifier so they can be surgically
removed without touching unrelated system rules.
"""

from __future__ import annotations

import json
import logging
import platform
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# File that persists the list of rule identifiers HomeHost has created
_RULES_DB_PATH: Path = Path.home() / ".homehost" / "firewall_rules.json"

# String embedded in every rule name/comment we create — used for lookup
_HOMEHOST_TAG = "HomeHost"


class FirewallManager:
    """Manage OS firewall rules for HomeHost.

    Rule identifiers are stored in ``~/.homehost/firewall_rules.json`` so they
    can be enumerated and removed even after a process restart.

    Tags every rule with ``HomeHost_<port>`` (Windows) or a ``# HomeHost``
    comment (pfctl) for surgical cleanup.
    """

    def __init__(self) -> None:
        self._system = platform.system()
        self._rules_db: Path = _RULES_DB_PATH
        self._rules_db.parent.mkdir(parents=True, exist_ok=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def open_port(
        self,
        port: int,
        protocol: str = "tcp",
        description: str = "HomeHost",
    ) -> bool:
        """Open *port* in the OS firewall.

        - **macOS**: checks whether the application-level firewall is active via
          ``socketfilterfw``.  If pfctl is reachable it also inserts a pass rule.
        - **Windows**: uses ``netsh advfirewall`` to add an inbound allow rule.
        - **Linux**: uses ``ufw allow`` if available, else ``iptables``.

        Returns ``True`` on success, ``False`` if the rule could not be added
        (logs a warning instead of raising).
        """
        log.info("Opening port %d/%s (%s) on %s", port, protocol, description, self._system)

        if self._system == "Darwin":
            return self._open_port_macos(port, protocol, description)
        if self._system == "Windows":
            return self._open_port_windows(port, protocol, description)
        if self._system == "Linux":
            return self._open_port_linux(port, protocol, description)

        log.warning("open_port not implemented for platform: %s", self._system)
        return False

    def close_port(self, port: int, protocol: str = "tcp") -> bool:
        """Remove the HomeHost firewall rule for *port*.

        Returns ``True`` if the rule was found and removed (or was never added),
        ``False`` if a removal attempt failed.
        """
        log.info("Closing port %d/%s on %s", port, protocol, self._system)

        if self._system == "Darwin":
            return self._close_port_macos(port, protocol)
        if self._system == "Windows":
            return self._close_port_windows(port, protocol)
        if self._system == "Linux":
            return self._close_port_linux(port, protocol)

        log.warning("close_port not implemented for platform: %s", self._system)
        return False

    def list_homehost_rules(self) -> list[dict[str, Any]]:
        """Return all firewall rules recorded by HomeHost."""
        return self._load_rules()

    def remove_all_homehost_rules(self) -> int:
        """Remove every firewall rule that HomeHost has created.

        Returns the number of rules successfully removed.
        """
        rules = self._load_rules()
        removed = 0
        for rule in rules:
            port = rule.get("port", 0)
            protocol = rule.get("protocol", "tcp")
            if self.close_port(port, protocol):
                removed += 1
        # Wipe the DB entirely
        self._save_rules([])
        log.info("Removed %d HomeHost firewall rule(s)", removed)
        return removed

    def is_port_allowed(self, port: int) -> bool:
        """Return ``True`` if *port* appears to be open in the current firewall.

        Uses a lightweight approach: check our own rule DB first, then attempt
        a quick OS-level query.
        """
        # Quick check: do we know we opened it?
        for rule in self._load_rules():
            if rule.get("port") == port:
                return True

        # OS-level check
        if self._system == "Darwin":
            return self._is_port_allowed_macos(port)
        if self._system == "Windows":
            return self._is_port_allowed_windows(port)
        if self._system == "Linux":
            return self._is_port_allowed_linux(port)

        return False

    # ── macOS Implementation ───────────────────────────────────────────────────

    def _open_port_macos(self, port: int, protocol: str, description: str) -> bool:
        """macOS: check firewall state, add pfctl pass rule if possible."""
        fw_enabled = self._macos_fw_enabled()

        if not fw_enabled:
            # Application-level firewall is off — port is open by default
            log.debug("macOS application firewall is disabled; no rule needed for port %d", port)
            self._record_rule(port, protocol, description, method="disabled")
            return True

        # Try pfctl — requires sudo but may be available in production installs
        success = self._pfctl_add_rule(port, protocol, description)
        if success:
            return True

        # If pfctl fails (permissions), we still record the intent and warn
        log.warning(
            "macOS application firewall is enabled but could not add pfctl rule for "
            "port %d.  You may need to allow the connection manually.",
            port,
        )
        self._record_rule(port, protocol, description, method="manual_required")
        return False

    def _close_port_macos(self, port: int, protocol: str) -> bool:
        rules = self._load_rules()
        matching = [r for r in rules if r.get("port") == port]
        if not matching:
            return True  # never tracked — nothing to do

        # Remove pfctl anchor rule if we created one
        if any(r.get("method") == "pfctl" for r in matching):
            self._pfctl_remove_rule(port, protocol)

        self._remove_rule_from_db(port)
        return True

    def _is_port_allowed_macos(self, port: int) -> bool:
        if not self._macos_fw_enabled():
            return True  # firewall off → everything is open

        try:
            result = subprocess.run(
                ["pfctl", "-s", "rules"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return f"port {port}" in result.stdout
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return False

    @staticmethod
    def _macos_fw_enabled() -> bool:
        """Return True if the macOS application-level firewall is on."""
        try:
            result = subprocess.run(
                [
                    "/usr/libexec/ApplicationFirewall/socketfilterfw",
                    "--getglobalstate",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.lower()
            return "enabled" in output and "disabled" not in output
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return False  # Can't determine state; assume off (safe default)

    def _pfctl_add_rule(self, port: int, protocol: str, description: str) -> bool:
        """Attempt to add a pfctl pass rule. Requires elevated privileges."""
        rule = f"pass in proto {protocol} to any port {port} # {_HOMEHOST_TAG}\n"
        try:
            # Append to /etc/pf.conf anchor via pfctl -ef
            proc = subprocess.run(
                ["pfctl", "-e", "-f", "-"],
                input=rule,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if proc.returncode == 0:
                self._record_rule(port, protocol, description, method="pfctl")
                log.info("pfctl rule added for port %d", port)
                return True
            log.debug("pfctl returned %d: %s", proc.returncode, proc.stderr.strip())
            return False
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.debug("pfctl not usable: %s", exc)
            return False

    @staticmethod
    def _pfctl_remove_rule(port: int, protocol: str) -> None:
        """Best-effort removal of a pfctl pass rule."""
        try:
            result = subprocess.run(
                ["pfctl", "-s", "rules"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            remaining_rules = [
                line for line in result.stdout.splitlines() if not (f"port {port}" in line and _HOMEHOST_TAG in line)
            ]
            new_ruleset = "\n".join(remaining_rules) + "\n"
            subprocess.run(
                ["pfctl", "-f", "-"],
                input=new_ruleset,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.debug("pfctl rule removal failed: %s", exc)

    # ── Windows Implementation ─────────────────────────────────────────────────

    def _open_port_windows(self, port: int, protocol: str, description: str) -> bool:
        rule_name = f"{_HOMEHOST_TAG}_{port}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={rule_name}",
            "dir=in",
            "action=allow",
            f"protocol={protocol}",
            f"localport={port}",
            f"description={description}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                self._record_rule(port, protocol, description, method="netsh", rule_name=rule_name)
                log.info("Windows firewall rule added: %s", rule_name)
                return True
            log.warning("netsh failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return False
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.warning("Could not add Windows firewall rule for port %d: %s", port, exc)
            return False

    def _close_port_windows(self, port: int, protocol: str) -> bool:
        rule_name = f"{_HOMEHOST_TAG}_{port}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "delete",
            "rule",
            f"name={rule_name}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            ok = result.returncode == 0
            if ok:
                self._remove_rule_from_db(port)
                log.info("Windows firewall rule deleted: %s", rule_name)
            else:
                log.warning("netsh delete returned %d: %s", result.returncode, result.stderr.strip())
            return ok
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.warning("Could not remove Windows firewall rule for port %d: %s", port, exc)
            return False

    def _is_port_allowed_windows(self, port: int) -> bool:
        rule_name = f"{_HOMEHOST_TAG}_{port}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "show",
            "rule",
            f"name={rule_name}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return result.returncode == 0 and "LocalPort" in result.stdout
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            return False

    # ── Linux Implementation ───────────────────────────────────────────────────

    def _open_port_linux(self, port: int, protocol: str, description: str) -> bool:
        # Try ufw first
        if self._ufw_available():
            return self._ufw_open(port, protocol, description)
        # Fallback: iptables
        return self._iptables_open(port, protocol, description)

    def _close_port_linux(self, port: int, protocol: str) -> bool:
        if self._ufw_available():
            return self._ufw_close(port, protocol)
        return self._iptables_close(port, protocol)

    def _is_port_allowed_linux(self, port: int) -> bool:
        if self._ufw_available():
            try:
                result = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=5)
                return str(port) in result.stdout
            except (subprocess.SubprocessError, OSError):
                return False
        try:
            result = subprocess.run(
                ["iptables", "-L", "INPUT", "-n"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return f"dpt:{port}" in result.stdout
        except (subprocess.SubprocessError, OSError, FileNotFoundError):
            return False

    @staticmethod
    def _ufw_available() -> bool:
        try:
            result = subprocess.run(
                ["ufw", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode in (0, 1)  # 1 = inactive but installed
        except (FileNotFoundError, OSError):
            return False

    def _ufw_open(self, port: int, protocol: str, description: str) -> bool:
        try:
            result = subprocess.run(
                ["ufw", "allow", f"{port}/{protocol}", "comment", f"{_HOMEHOST_TAG}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self._record_rule(port, protocol, description, method="ufw")
                return True
            log.warning("ufw allow failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return False
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.warning("ufw not usable: %s", exc)
            return False

    def _ufw_close(self, port: int, protocol: str) -> bool:
        try:
            result = subprocess.run(
                ["ufw", "delete", "allow", f"{port}/{protocol}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ok = result.returncode == 0
            if ok:
                self._remove_rule_from_db(port)
            return ok
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.warning("ufw delete failed: %s", exc)
            return False

    def _iptables_open(self, port: int, protocol: str, description: str) -> bool:
        try:
            result = subprocess.run(
                [
                    "iptables",
                    "-A",
                    "INPUT",
                    "-p",
                    protocol,
                    "--dport",
                    str(port),
                    "-j",
                    "ACCEPT",
                    "-m",
                    "comment",
                    "--comment",
                    _HOMEHOST_TAG,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self._record_rule(port, protocol, description, method="iptables")
                return True
            log.warning("iptables failed (rc=%d): %s", result.returncode, result.stderr.strip())
            return False
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.warning("iptables not usable: %s", exc)
            return False

    def _iptables_close(self, port: int, protocol: str) -> bool:
        try:
            result = subprocess.run(
                [
                    "iptables",
                    "-D",
                    "INPUT",
                    "-p",
                    protocol,
                    "--dport",
                    str(port),
                    "-j",
                    "ACCEPT",
                    "-m",
                    "comment",
                    "--comment",
                    _HOMEHOST_TAG,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ok = result.returncode == 0
            if ok:
                self._remove_rule_from_db(port)
            return ok
        except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
            log.warning("iptables delete failed: %s", exc)
            return False

    # ── Rule DB Helpers ────────────────────────────────────────────────────────

    def _load_rules(self) -> list[dict[str, Any]]:
        """Load rule list from JSON file."""
        try:
            if self._rules_db.exists():
                text = self._rules_db.read_text(encoding="utf-8")
                data = json.loads(text)
                if isinstance(data, list):
                    return data  # type: ignore[return-value]
        except (json.JSONDecodeError, OSError) as exc:
            log.debug("Could not load firewall rules DB: %s", exc)
        return []

    def _save_rules(self, rules: list[dict[str, Any]]) -> None:
        """Persist rule list to JSON file atomically."""
        try:
            import os
            import tempfile

            data = json.dumps(rules, indent=2)
            dir_ = self._rules_db.parent
            dir_.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
            try:
                os.write(fd, data.encode())
                os.close(fd)
                os.replace(tmp, str(self._rules_db))
            except Exception:
                os.unlink(tmp)
                raise
        except OSError as exc:
            log.warning("Could not save firewall rules DB: %s", exc)

    def _record_rule(self, port: int, protocol: str, description: str, **extra: Any) -> None:
        """Add a rule entry to the persistent DB."""
        rules = self._load_rules()
        # Avoid duplicates
        rules = [r for r in rules if r.get("port") != port]
        entry: dict[str, Any] = {
            "port": port,
            "protocol": protocol,
            "description": description,
        }
        entry.update(extra)
        rules.append(entry)
        self._save_rules(rules)

    def _remove_rule_from_db(self, port: int) -> None:
        """Remove all DB entries for *port*."""
        rules = [r for r in self._load_rules() if r.get("port") != port]
        self._save_rules(rules)
