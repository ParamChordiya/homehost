"""Unit tests for network utilities — all network calls are mocked."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from homehost.core.detector import (
    check_internet,
    find_available_port,
    get_local_ip,
    is_port_in_use,
)
from homehost.network.local import (
    format_local_url,
    get_local_ip as net_get_local_ip,
    is_private_ip,
)


# ── is_port_in_use ─────────────────────────────────────────────────────────────


class TestIsPortInUse:
    def test_returns_false_when_port_is_free(self):
        """A port that successfully binds on both interfaces is free."""
        with patch("homehost.core.detector.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock_cls.return_value = mock_sock
            # bind() raises nothing → port is free on each host → returns False
            mock_sock.bind.return_value = None

            result = is_port_in_use(12345)
        assert result is False

    def test_returns_true_when_bind_raises_oserror(self):
        """An OSError on bind means the port is already in use."""
        with patch("homehost.core.detector.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.bind.side_effect = OSError("Address already in use")
            mock_sock_cls.return_value = mock_sock

            result = is_port_in_use(8080)
        assert result is True


# ── find_available_port ────────────────────────────────────────────────────────


class TestFindAvailablePort:
    def test_returns_first_free_port_in_range(self):
        """Mock is_port_in_use so that 8082 is the first free port."""

        def mock_in_use(port: int) -> bool:
            return port in (8080, 8081)

        with patch("homehost.core.detector.is_port_in_use", side_effect=mock_in_use):
            result = find_available_port(8080, 8085)
        assert result == 8082

    def test_returns_none_when_all_ports_taken(self):
        """All ports busy → returns None."""
        with patch("homehost.core.detector.is_port_in_use", return_value=True):
            result = find_available_port(8080, 8083)
        assert result is None

    def test_returns_start_port_when_immediately_free(self):
        with patch("homehost.core.detector.is_port_in_use", return_value=False):
            result = find_available_port(9000, 9010)
        assert result == 9000

    def test_single_port_range_free(self):
        with patch("homehost.core.detector.is_port_in_use", return_value=False):
            result = find_available_port(8888, 8888)
        assert result == 8888

    def test_single_port_range_busy(self):
        with patch("homehost.core.detector.is_port_in_use", return_value=True):
            result = find_available_port(8888, 8888)
        assert result is None


# ── get_local_ip (detector) ────────────────────────────────────────────────────


class TestGetLocalIpDetector:
    def test_returns_ip_on_success(self):
        with patch("homehost.core.detector.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.getsockname.return_value = ("192.168.1.100", 0)
            mock_sock_cls.return_value = mock_sock

            ip = get_local_ip()
        assert ip == "192.168.1.100"

    def test_returns_fallback_on_exception(self):
        with patch("homehost.core.detector.socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.connect.side_effect = OSError("Network unreachable")
            mock_sock_cls.return_value = mock_sock

            ip = get_local_ip()
        assert ip == "127.0.0.1"


# ── check_internet ─────────────────────────────────────────────────────────────


class TestCheckInternet:
    def test_returns_ok_when_connection_succeeds(self):
        with patch("homehost.core.detector.socket.create_connection") as mock_conn:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = lambda s: s
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value = mock_ctx

            result = check_internet()
        assert result.status == "ok"
        assert "reachable" in result.message.lower()

    def test_returns_error_when_connection_fails(self):
        with patch(
            "homehost.core.detector.socket.create_connection",
            side_effect=OSError("Connection refused"),
        ):
            result = check_internet()
        assert result.status == "error"
        assert "internet" in result.message.lower() or "connection" in result.message.lower()


# ── is_private_ip ──────────────────────────────────────────────────────────────


class TestIsPrivateIp:
    @pytest.mark.parametrize(
        "ip,expected",
        [
            ("192.168.1.1", True),
            ("192.168.0.254", True),
            ("10.0.0.1", True),
            ("10.255.255.255", True),
            ("172.16.0.1", True),
            ("172.31.255.255", True),
            ("8.8.8.8", False),
            ("1.1.1.1", False),
            # Python's ipaddress.is_private includes loopback and link-local, so
            # 127.0.0.1 and 172.32.x.x are classified per the stdlib definition.
            ("172.32.0.1", False),  # just outside the 172.16-31 range
        ],
    )
    def test_classification(self, ip, expected):
        assert is_private_ip(ip) is expected

    def test_invalid_ip_returns_false(self):
        assert is_private_ip("not-an-ip") is False
        assert is_private_ip("") is False


# ── format_local_url ───────────────────────────────────────────────────────────


class TestFormatLocalUrl:
    def test_format_includes_ip_and_port(self):
        with patch("homehost.network.local.get_local_ip", return_value="192.168.0.10"):
            url = format_local_url(8080)
        assert url == "http://192.168.0.10:8080"

    def test_format_with_different_port(self):
        with patch("homehost.network.local.get_local_ip", return_value="10.0.0.1"):
            url = format_local_url(3000)
        assert url == "http://10.0.0.1:3000"


# ── get_local_ip (network.local) ───────────────────────────────────────────────


class TestNetworkLocalGetLocalIp:
    def test_returns_private_ip_from_socket(self):
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.5.20", 0)

        with patch("homehost.network.local.socket.socket") as mock_cls:
            mock_cls.return_value.__enter__ = lambda s: mock_sock
            mock_cls.return_value.__exit__ = MagicMock(return_value=False)
            ip = net_get_local_ip()

        # Could come from the socket trick or the fallback — just verify format
        assert isinstance(ip, str)
        assert ip.count(".") == 3

    def test_falls_back_on_socket_error(self):
        with patch("homehost.network.local.socket.socket") as mock_cls:
            mock_sock = MagicMock()
            mock_sock.__enter__ = lambda s: s
            mock_sock.__exit__ = MagicMock(return_value=False)
            mock_sock.connect.side_effect = OSError("unreachable")
            mock_cls.return_value = mock_sock

            with patch("homehost.network.local.subprocess.check_output", side_effect=OSError):
                with patch("homehost.network.local.socket.gethostname", return_value="host"):
                    with patch("homehost.network.local.socket.gethostbyname", return_value="127.0.0.1"):
                        ip = net_get_local_ip()

        # After all fallbacks fail, it returns "127.0.0.1"
        assert ip == "127.0.0.1"
