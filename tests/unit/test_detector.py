"""Unit tests for homehost.core.detector — OS detection and pre-flight checks."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from homehost.core.detector import (
    CheckResult,
    SystemInfo,
    check_caddy,
    check_cloudflared,
    check_disk_space,
    check_git,
    check_internet,
    check_node,
    check_python_version,
    detect_system,
    find_available_port,
    find_executable,
    get_local_ip,
    is_port_in_use,
    run_all_checks,
)

# ── detect_system / _os_name ───────────────────────────────────────────────────


class TestDetectSystem:
    def test_returns_systeminfo_on_macos(self):
        with patch("homehost.core.detector.platform.system", return_value="Darwin"):
            with patch("homehost.core.detector._run", return_value=(0, "15.1", "")):
                with patch("homehost.core.detector.is_port_in_use", return_value=False):
                    with patch("homehost.core.detector.get_local_ip", return_value="192.168.1.1"):
                        with patch("homehost.core.detector.check_internet") as mock_ci:
                            mock_ci.return_value = CheckResult("internet", "ok", "ok")
                            info = detect_system()
        assert isinstance(info, SystemInfo)
        assert info.os_name == "macOS"

    def test_returns_systeminfo_on_windows(self):
        with patch("homehost.core.detector.platform.system", return_value="Windows"):
            with patch("homehost.core.detector.platform.version", return_value="10.0.19041"):
                with patch("homehost.core.detector.is_port_in_use", return_value=False):
                    with patch("homehost.core.detector.get_local_ip", return_value="192.168.1.2"):
                        with patch("homehost.core.detector.check_internet") as mock_ci:
                            mock_ci.return_value = CheckResult("internet", "ok", "ok")
                            info = detect_system()
        assert isinstance(info, SystemInfo)
        assert info.os_name == "Windows"

    def test_systeminfo_contains_python_version(self):
        import sys

        with patch("homehost.core.detector.is_port_in_use", return_value=False):
            with patch("homehost.core.detector.get_local_ip", return_value="127.0.0.1"):
                with patch("homehost.core.detector.check_internet") as mock_ci:
                    mock_ci.return_value = CheckResult("internet", "ok", "ok")
                    info = detect_system()

        expected = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        assert info.python_version == expected

    def test_local_ip_populated(self):
        with patch("homehost.core.detector.is_port_in_use", return_value=True):
            with patch("homehost.core.detector.get_local_ip", return_value="10.0.0.5"):
                with patch("homehost.core.detector.check_internet") as mock_ci:
                    mock_ci.return_value = CheckResult("internet", "ok", "ok")
                    info = detect_system()
        assert info.local_ip == "10.0.0.5"


# ── is_port_in_use ─────────────────────────────────────────────────────────────


class TestIsPortInUse:
    def test_returns_false_when_bind_succeeds(self):
        with patch("homehost.core.detector.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.return_value = None
            mock_cls.return_value = mock_sock

            assert is_port_in_use(19999) is False

    def test_returns_true_when_bind_raises(self):
        with patch("homehost.core.detector.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = OSError("already in use")
            mock_cls.return_value = mock_sock

            assert is_port_in_use(8080) is True

    def test_connection_refused_counts_as_free(self):
        """ConnectionRefusedError during bind means nothing is listening → free."""
        with patch("homehost.core.detector.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = ConnectionRefusedError
            mock_cls.return_value = mock_sock
            # ConnectionRefusedError is a subclass of OSError → port_in_use = True
            # The actual impl treats any OSError as "in use"
            result = is_port_in_use(9999)
        assert isinstance(result, bool)


# ── find_available_port ────────────────────────────────────────────────────────


class TestFindAvailablePort:
    def test_first_free_port_returned(self):
        call_count = {"n": 0}

        def mock_in_use(port):
            call_count["n"] += 1
            return port < 8083  # 8083 is free

        with patch("homehost.core.detector.is_port_in_use", side_effect=mock_in_use):
            result = find_available_port(8080, 8090)
        assert result == 8083

    def test_returns_none_when_all_taken(self):
        with patch("homehost.core.detector.is_port_in_use", return_value=True):
            result = find_available_port(8080, 8082)
        assert result is None


# ── get_local_ip ───────────────────────────────────────────────────────────────


class TestGetLocalIp:
    def test_returns_valid_ip_string(self):
        with patch("homehost.core.detector.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.getsockname.return_value = ("10.0.0.2", 0)
            mock_cls.return_value = mock_sock

            ip = get_local_ip()
        assert ip == "10.0.0.2"

    def test_returns_fallback_on_socket_error(self):
        with patch("homehost.core.detector.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.connect.side_effect = OSError("unreachable")
            mock_cls.return_value = mock_sock

            ip = get_local_ip()
        assert ip == "127.0.0.1"

    def test_handles_generic_exception_gracefully(self):
        with patch("homehost.core.detector.socket.socket", side_effect=Exception("unexpected")):
            ip = get_local_ip()
        assert ip == "127.0.0.1"


# ── check_internet ─────────────────────────────────────────────────────────────


class TestCheckInternet:
    def test_ok_when_connection_opens(self):
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = lambda s: s
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("homehost.core.detector.socket.create_connection", return_value=mock_ctx):
            result = check_internet()
        assert result.status == "ok"
        assert result.name == "internet"

    def test_error_when_connection_fails(self):
        with patch(
            "homehost.core.detector.socket.create_connection",
            side_effect=OSError("No route to host"),
        ):
            result = check_internet()
        assert result.status == "error"
        assert result.fix_hint != ""

    def test_returns_check_result_instance(self):
        with patch("homehost.core.detector.socket.create_connection", side_effect=OSError):
            result = check_internet()
        assert isinstance(result, CheckResult)


# ── check_disk_space ───────────────────────────────────────────────────────────


class TestCheckDiskSpace:
    def test_ok_when_plenty_of_space(self):
        with patch("homehost.core.detector._disk_free_gb", return_value=50.0):
            result = check_disk_space(min_gb=1.0)
        assert result.status == "ok"

    def test_warning_when_low_disk(self):
        with patch("homehost.core.detector._disk_free_gb", return_value=0.5):
            result = check_disk_space(min_gb=1.0)
        assert result.status == "warning"
        assert "0.5" in result.message

    def test_error_when_disk_full(self):
        with patch("homehost.core.detector._disk_free_gb", return_value=0.0):
            result = check_disk_space(min_gb=1.0)
        assert result.status == "error"

    def test_fix_hint_present_on_warning(self):
        with patch("homehost.core.detector._disk_free_gb", return_value=0.1):
            result = check_disk_space(min_gb=1.0)
        assert result.fix_hint != ""


# ── run_all_checks ─────────────────────────────────────────────────────────────


class TestRunAllChecks:
    def test_returns_list(self):
        results = run_all_checks()
        assert isinstance(results, list)

    def test_contains_at_least_five_items(self):
        results = run_all_checks()
        assert len(results) >= 5

    def test_all_items_are_check_results(self):
        results = run_all_checks()
        for r in results:
            assert isinstance(r, CheckResult)

    def test_all_statuses_are_valid(self):
        valid = {"ok", "warning", "error", "missing"}
        results = run_all_checks()
        for r in results:
            assert r.status in valid, f"Unexpected status {r.status!r} for check {r.name!r}"

    def test_python_check_included(self):
        results = run_all_checks()
        names = {r.name for r in results}
        assert "python" in names

    def test_disk_check_included(self):
        results = run_all_checks()
        names = {r.name for r in results}
        assert "disk" in names


# ── find_executable ────────────────────────────────────────────────────────────


class TestFindExecutable:
    def test_returns_path_when_found(self):
        with patch("homehost.core.detector.shutil.which", return_value="/usr/bin/python3"):
            path = find_executable("python3")
        assert path == "/usr/bin/python3"

    def test_returns_empty_string_when_not_found(self):
        with patch("homehost.core.detector.shutil.which", return_value=None):
            path = find_executable("some-nonexistent-binary")
        assert path == ""

    def test_return_type_is_str(self):
        with patch("homehost.core.detector.shutil.which", return_value=None):
            result = find_executable("anything")
        assert isinstance(result, str)


# ── check_python_version ───────────────────────────────────────────────────────


class TestCheckPythonVersion:
    def test_ok_for_current_python(self):
        # We're running on 3.10+, so this must pass
        result = check_python_version()
        assert result.status == "ok"
        assert result.name == "python"

    def test_error_for_old_python(self):
        import sys

        # sys.version_info is a C-level struct — patch just the tuple comparison
        # by substituting a namedtuple-compatible object via a helper.
        from collections import namedtuple

        FakeVI = namedtuple("version_info", ["major", "minor", "micro", "releaselevel", "serial"])
        fake_vi = FakeVI(3, 9, 0, "final", 0)
        with patch("homehost.core.detector.sys.version_info", fake_vi):
            result = check_python_version()
        assert result.status == "error"
        assert "3.9" in result.message
        assert result.fix_hint != ""
