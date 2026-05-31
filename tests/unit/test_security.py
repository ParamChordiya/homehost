"""Unit tests for homehost security modules."""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from homehost.security.hardening import (
    check_security_posture,
    generate_dotfile_block,
    generate_security_headers_caddy_block,
    SECURITY_HEADERS,
)
from homehost.security.secrets import (
    generate_strong_password,
    hash_password,
    verify_password,
)

# ── hash_password ──────────────────────────────────────────────────────────────


class TestHashPassword:
    def test_returns_bcrypt_hash(self):
        h = hash_password("mysecret")
        assert h.startswith("$2b$")

    def test_hash_is_string(self):
        h = hash_password("another")
        assert isinstance(h, str)

    def test_two_hashes_of_same_password_differ(self):
        """bcrypt uses random salt, so hashes must differ."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_hash_not_plaintext(self):
        pw = "supersecret123"
        h = hash_password(pw)
        assert pw not in h


# ── verify_password ────────────────────────────────────────────────────────────


class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        pw = "correct-horse-battery"
        h = hash_password(pw)
        assert verify_password(pw, h) is True

    def test_wrong_password_returns_false(self):
        h = hash_password("rightpassword")
        assert verify_password("wrongpassword", h) is False

    def test_empty_password_wrong_hash_returns_false(self):
        h = hash_password("notempty")
        assert verify_password("", h) is False

    def test_invalid_hash_returns_false(self):
        """Garbage hash should not raise — just return False."""
        assert verify_password("anypassword", "not-a-valid-bcrypt-hash") is False

    def test_hash_is_never_stored_plaintext(self):
        pw = "plaintext-danger"
        h = hash_password(pw)
        # The hash must not contain the raw password
        assert pw not in h


# ── generate_strong_password ───────────────────────────────────────────────────


class TestGenerateStrongPassword:
    def test_default_length_segments(self):
        pw = generate_strong_password()
        # The alphabet includes "-", so segments themselves may contain dashes.
        # The implementation joins 4 fixed-length segments with "-" separators.
        # Each segment is length//4 == 4 chars, and the separators are at positions 4, 9, 14.
        # Verify: stripping the 3 separator dashes leaves exactly 16 characters.
        segment_size = 4
        sep_count = 3
        # Find segment boundaries by index (segment_size + 1 chars per group including separator)
        stride = segment_size + 1  # 5
        # Check: 4 segments of 4 chars each, with 3 single-char separators between them
        # Total length = 4*4 + 3 = 19 chars
        assert len(pw) == segment_size * 4 + sep_count
        # The separating dash between each pair of segments is at a fixed stride
        for i in range(1, 4):
            assert pw[i * stride - 1] == "-", f"Expected separator at index {i * stride - 1}"

    def test_custom_length(self):
        pw = generate_strong_password(20)
        # Total string length = 20 chars + 3 separator dashes = 23
        # (The alphabet itself contains "-", so we can't strip all dashes.)
        assert len(pw) == 20 + 3

    def test_length_rounded_up_to_multiple_of_4(self):
        pw = generate_strong_password(7)
        chars_no_dash = pw.replace("-", "")
        # 7 → rounded up to 8
        assert len(chars_no_dash) == 8

    def test_characters_from_allowed_alphabet(self):
        allowed = set(string.ascii_letters + string.digits + "!@#$%^&*-_=+")
        pw = generate_strong_password(16)
        for ch in pw:
            assert ch in allowed

    def test_two_calls_produce_different_passwords(self):
        p1 = generate_strong_password()
        p2 = generate_strong_password()
        assert p1 != p2

    def test_minimum_length_of_4(self):
        pw = generate_strong_password(1)
        chars_no_dash = pw.replace("-", "")
        assert len(chars_no_dash) == 4

    def test_has_four_segments_separated_by_dashes(self):
        pw = generate_strong_password(16)
        # The alphabet contains "-", so the total dash count may exceed 3.
        # What we can guarantee is that 3 separator dashes exist at fixed stride
        # positions (4, 9, 14 for segment_size=4).
        segment_size = 4
        for i in range(1, 4):
            idx = i * (segment_size + 1) - 1
            assert pw[idx] == "-", f"Expected separator dash at index {idx}, got {pw[idx]!r}"


# ── generate_security_headers_caddy_block ─────────────────────────────────────


class TestGenerateSecurityHeadersCaddyBlock:
    def test_returns_header_block_string(self):
        block = generate_security_headers_caddy_block()
        assert isinstance(block, str)
        assert block.startswith("header {")
        assert block.endswith("}")

    def test_contains_all_required_headers(self):
        block = generate_security_headers_caddy_block()
        for header_name in SECURITY_HEADERS:
            assert header_name in block, f"Missing header: {header_name}"

    def test_removes_server_header(self):
        block = generate_security_headers_caddy_block()
        assert "-Server" in block

    def test_removes_x_powered_by(self):
        block = generate_security_headers_caddy_block()
        assert "-X-Powered-By" in block

    def test_contains_csp(self):
        block = generate_security_headers_caddy_block()
        assert "Content-Security-Policy" in block

    def test_contains_hsts(self):
        block = generate_security_headers_caddy_block()
        assert "Strict-Transport-Security" in block

    def test_contains_x_frame_options(self):
        block = generate_security_headers_caddy_block()
        assert "X-Frame-Options" in block


# ── generate_dotfile_block ─────────────────────────────────────────────────────


class TestGenerateDotfileBlock:
    def test_returns_non_empty_string(self):
        block = generate_dotfile_block()
        assert isinstance(block, str)
        assert len(block) > 0

    def test_contains_dotfile_path_regexp(self):
        block = generate_dotfile_block()
        assert "@dotfiles" in block
        assert "path_regexp" in block

    def test_contains_respond_403(self):
        block = generate_dotfile_block()
        assert "respond" in block
        assert "403" in block

    def test_blocks_sensitive_paths(self):
        block = generate_dotfile_block()
        assert ".env" in block
        assert ".git" in block


# ── validate_subdomain (via check_security_posture indirectly) ─────────────────


class TestCheckSecurityPosture:
    def test_detects_env_file_as_high_severity(self, temp_dir):
        (temp_dir / ".env").write_text("SECRET_KEY=abc123\n")
        findings = check_security_posture(str(temp_dir), "static")
        assert any(f["severity"] == "high" for f in findings)
        high_titles = [f["title"] for f in findings if f["severity"] == "high"]
        assert any("env" in t.lower() or "environment" in t.lower() for t in high_titles)

    def test_returns_list_for_valid_directory(self, temp_dir):
        findings = check_security_posture(str(temp_dir), "static")
        assert isinstance(findings, list)

    def test_returns_info_finding_for_nonexistent_dir(self, temp_dir):
        missing = str(temp_dir / "no-such-dir")
        findings = check_security_posture(missing, "static")
        assert len(findings) >= 1
        assert findings[0]["severity"] == "info"

    def test_git_dir_is_medium_severity(self, temp_dir):
        (temp_dir / ".git").mkdir()
        findings = check_security_posture(str(temp_dir), "static")
        severities = [f["severity"] for f in findings]
        assert "medium" in severities

    def test_flask_type_generates_https_warning(self, temp_dir):
        findings = check_security_posture(str(temp_dir), "flask")
        assert any("https" in f["title"].lower() or "HTTPS" in f["title"] for f in findings)

    def test_findings_sorted_by_severity_high_first(self, temp_dir):
        (temp_dir / ".env").write_text("TOKEN=secret\n")
        (temp_dir / ".git").mkdir()
        findings = check_security_posture(str(temp_dir), "flask")
        order = {"high": 0, "medium": 1, "low": 2, "info": 3}
        severity_indices = [order[f["severity"]] for f in findings]
        assert severity_indices == sorted(severity_indices)

    def test_all_findings_have_required_keys(self, temp_dir):
        (temp_dir / ".env").write_text("X=1\n")
        findings = check_security_posture(str(temp_dir), "flask")
        for f in findings:
            assert "severity" in f
            assert "title" in f
            assert "description" in f
            assert "fix" in f

    def test_severity_values_are_valid(self, temp_dir):
        valid_severities = {"high", "medium", "low", "info"}
        findings = check_security_posture(str(temp_dir), "node")
        for f in findings:
            assert f["severity"] in valid_severities

    def test_unpinned_sensitive_deps_flagged(self, temp_dir):
        (temp_dir / "requirements.txt").write_text("flask>=3.0\ndjango>=4.2\n")
        findings = check_security_posture(str(temp_dir), "flask")
        assert any("unpinned" in f["title"].lower() or "sensitive" in f["title"].lower() for f in findings)
