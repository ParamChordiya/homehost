"""SSL certificate status and inspection helpers for HomeHost."""

from __future__ import annotations

import datetime
import logging
import socket
import ssl
from typing import Any

log = logging.getLogger(__name__)

# Timeout (seconds) for SSL handshake / socket operations
_SSL_TIMEOUT: float = 8.0


def check_ssl_cert(hostname: str, port: int = 443) -> dict[str, Any]:
    """Check the SSL certificate for *hostname*:*port*.

    Returns a dict::

        {
            "valid":   bool,   # True if cert is present, not expired, and CN matches
            "expires": str,    # ISO-8601 expiry date, e.g. "2025-03-15T12:00:00"
            "issuer":  str,    # Human-readable issuer string
            "error":   str,    # Non-empty if something went wrong
        }

    All network and SSL errors are caught; *error* is set and *valid* is False.
    A 8-second timeout is applied to the socket connection.
    """
    result: dict[str, Any] = {
        "valid": False,
        "expires": "",
        "issuer": "",
        "error": "",
    }

    context = ssl.create_default_context()

    try:
        with socket.create_connection((hostname, port), timeout=_SSL_TIMEOUT) as raw_sock:
            with context.wrap_socket(raw_sock, server_hostname=hostname) as ssl_sock:
                cert: dict[str, Any] = ssl_sock.getpeercert()  # type: ignore[assignment]

                # ── Expiry ────────────────────────────────────────────────────
                not_after_str: str = cert.get("notAfter", "")
                if not_after_str:
                    not_after = _parse_cert_date(not_after_str)
                    result["expires"] = not_after.isoformat()
                    now = datetime.datetime.now(tz=datetime.timezone.utc)
                    if not_after <= now:
                        result["error"] = f"Certificate expired on {not_after.isoformat()}"
                        return result
                else:
                    result["error"] = "Certificate missing 'notAfter' field"
                    return result

                # ── Issuer ────────────────────────────────────────────────────
                issuer_raw = cert.get("issuer", ())
                result["issuer"] = _format_distinguished_name(issuer_raw)

                # ── Subject / CN match ────────────────────────────────────────
                # ssl.create_default_context() already performs hostname
                # verification during wrap_socket; if we reach here the cert
                # is valid for this hostname.
                result["valid"] = True

    except ssl.CertificateError as exc:
        result["error"] = f"Certificate hostname mismatch or invalid: {exc}"
    except ssl.SSLError as exc:
        result["error"] = f"SSL error: {exc}"
    except (socket.timeout, TimeoutError):
        result["error"] = f"Connection timed out after {_SSL_TIMEOUT:.0f} s"
    except ConnectionRefusedError:
        result["error"] = f"Connection refused on {hostname}:{port}"
    except socket.gaierror as exc:
        result["error"] = f"DNS resolution failed for {hostname!r}: {exc}"
    except OSError as exc:
        result["error"] = f"Network error: {exc}"

    return result


def days_until_expiry(hostname: str, port: int = 443) -> int:
    """Return the number of whole days until *hostname*'s SSL cert expires.

    Returns ``-1`` on any error (network failure, invalid cert, DNS miss, etc.).
    Returns ``0`` if the cert expired today.
    Returns a negative number less than ``-1`` … wait, we clamp to ``-1`` for all
    errors so callers can use a simple ``days >= 0`` guard.
    """
    cert_info = check_ssl_cert(hostname, port)

    if not cert_info["valid"] and not cert_info["expires"]:
        log.debug(
            "days_until_expiry(%r): cert check failed: %s", hostname, cert_info["error"]
        )
        return -1

    expires_str = cert_info.get("expires", "")
    if not expires_str:
        return -1

    try:
        expires = datetime.datetime.fromisoformat(expires_str)
        if expires.tzinfo is None:
            # Treat naive datetime as UTC
            expires = expires.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        delta = expires - now
        days = max(0, delta.days)
        return days
    except (ValueError, OverflowError) as exc:
        log.debug("days_until_expiry: could not parse expiry %r: %s", expires_str, exc)
        return -1


# ── Private helpers ────────────────────────────────────────────────────────────


def _parse_cert_date(date_str: str) -> datetime.datetime:
    """Parse a certificate date string (RFC 2459 / ASN.1 GeneralizedTime).

    Python's ``ssl`` module returns dates in the format
    ``"May 15 12:00:00 2026 GMT"`` or ``"Jan  5 00:00:00 2026 GMT"``.
    Falls back to a manual strptime parse if the built-in approach fails.
    """
    # ssl.cert_time_to_seconds returns epoch seconds
    try:
        epoch = ssl.cert_time_to_seconds(date_str)
        return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass

    # Manual fallback — some OpenSSL builds use slightly different formatting
    for fmt in (
        "%b %d %H:%M:%S %Y %Z",
        "%b  %d %H:%M:%S %Y %Z",  # zero-padded day with leading space
        "%Y%m%d%H%M%SZ",          # ASN.1 GeneralizedTime
    ):
        try:
            dt = datetime.datetime.strptime(date_str.strip(), fmt)
            # Force UTC if the format consumed the timezone token
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except ValueError:
            continue

    raise ValueError(f"Cannot parse certificate date: {date_str!r}")


def _format_distinguished_name(dn_tuples: Any) -> str:
    """Convert the nested-tuple DN from ``getpeercert()`` to a readable string.

    Example input (from Python's ssl module)::

        ((('organizationName', 'Let\\'s Encrypt'),), (('commonName', 'R11'),))

    Example output::

        "O=Let's Encrypt, CN=R11"

    Short-name mapping covers the most common RDN attribute types.
    """
    _ATTR_SHORT: dict[str, str] = {
        "commonName": "CN",
        "organizationName": "O",
        "organizationalUnitName": "OU",
        "countryName": "C",
        "stateOrProvinceName": "ST",
        "localityName": "L",
        "emailAddress": "E",
        "serialNumber": "SN",
    }

    parts: list[str] = []
    try:
        for rdn in dn_tuples:
            for attr_type, attr_value in rdn:
                short = _ATTR_SHORT.get(attr_type, attr_type)
                parts.append(f"{short}={attr_value}")
    except (TypeError, ValueError):
        return str(dn_tuples)

    return ", ".join(parts)
