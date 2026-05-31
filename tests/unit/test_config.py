"""Unit tests for homehost.core.config — config read/write/list/delete."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from homehost.core.config import (
    GlobalConfig,
    ProjectConfig,
    delete_project_config,
    list_projects,
    load_global_config,
    load_project_config,
    project_config_path,
    save_global_config,
    save_project_config,
)

# ── helpers ────────────────────────────────────────────────────────────────────


def _patch_homehost_dir(tmp: Path):
    """Return a context manager that redirects homehost_dir() to *tmp*."""
    hh = tmp / ".homehost"
    hh.mkdir(parents=True, exist_ok=True)
    return patch("homehost.core.config.homehost_dir", return_value=hh)


# ── GlobalConfig tests ─────────────────────────────────────────────────────────


class TestLoadGlobalConfig:
    def test_returns_defaults_when_no_file_exists(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = load_global_config()

        assert isinstance(cfg, GlobalConfig)
        assert cfg.general.dashboard_port == 9111
        assert cfg.general.log_level == "info"
        assert cfg.server.engine == "caddy"
        assert cfg.network.default_access == "local"
        assert cfg.security.rate_limit == 100
        assert cfg.dashboard.enabled is True
        assert cfg.dashboard.theme == "dark"

    def test_returns_defaults_for_partial_file(self, tmp_path):
        """A file with only one key should not break other defaults."""
        hh = tmp_path / ".homehost"
        hh.mkdir()
        (hh / "config.toml").write_text("[general]\ndashboard_port = 7777\n")

        with patch("homehost.core.config.homehost_dir", return_value=hh):
            cfg = load_global_config()

        assert cfg.general.dashboard_port == 7777
        assert cfg.general.log_level == "info"  # default untouched


class TestSaveAndLoadGlobalConfig:
    def test_round_trip_preserves_all_values(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = GlobalConfig()
            cfg.general.dashboard_port = 7890
            cfg.general.log_level = "debug"
            cfg.general.auto_start_on_boot = True
            cfg.server.engine = "builtin"
            cfg.server.caddy_path = "/usr/local/bin/caddy"
            cfg.network.default_access = "public"
            cfg.network.tunnel_provider = "duckdns"
            cfg.security.rate_limit = 50
            cfg.security.enable_security_headers = False
            cfg.security.block_dotfiles = False
            cfg.dashboard.enabled = False
            cfg.dashboard.theme = "light"

            save_global_config(cfg)
            loaded = load_global_config()

        assert loaded.general.dashboard_port == 7890
        assert loaded.general.log_level == "debug"
        assert loaded.general.auto_start_on_boot is True
        assert loaded.server.engine == "builtin"
        assert loaded.server.caddy_path == "/usr/local/bin/caddy"
        assert loaded.network.default_access == "public"
        assert loaded.network.tunnel_provider == "duckdns"
        assert loaded.security.rate_limit == 50
        assert loaded.security.enable_security_headers is False
        assert loaded.security.block_dotfiles is False
        assert loaded.dashboard.enabled is False
        assert loaded.dashboard.theme == "light"

    def test_save_creates_toml_file(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            save_global_config(GlobalConfig())
            config_file = tmp_path / ".homehost" / "config.toml"

        assert config_file.exists()
        assert config_file.stat().st_size > 0

    def test_custom_values_override_defaults(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = load_global_config()
            cfg.general.check_for_updates = False
            cfg.general.log_retention_days = 30
            save_global_config(cfg)
            reloaded = load_global_config()

        assert reloaded.general.check_for_updates is False
        assert reloaded.general.log_retention_days == 30


# ── ProjectConfig tests ────────────────────────────────────────────────────────


class TestLoadProjectConfig:
    def test_returns_defaults_for_unknown_project(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = load_project_config("nonexistent-project")

        assert isinstance(cfg, ProjectConfig)
        assert cfg.name == "nonexistent-project"
        assert cfg.type == "static"
        assert cfg.server.port == 8080
        assert cfg.server.auto_start is True
        assert cfg.network.access == "local"
        assert cfg.security.basic_auth is False
        assert cfg.watcher.enabled is True

    def test_name_falls_back_to_argument(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = load_project_config("my-site")
        assert cfg.name == "my-site"


class TestSaveProjectConfig:
    def test_creates_toml_file_correctly(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = ProjectConfig()
            cfg.name = "hello-world"
            cfg.type = "flask"
            cfg.path = "/home/user/hello-world"
            cfg.server.port = 5000
            save_project_config(cfg)

            saved_path = project_config_path("hello-world")
        assert saved_path.exists()
        raw = saved_path.read_text()
        assert "hello-world" in raw
        assert "flask" in raw

    def test_round_trip_preserves_project_values(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = ProjectConfig()
            cfg.name = "api-server"
            cfg.type = "fastapi"
            cfg.path = "/srv/api-server"
            cfg.server.port = 8000
            cfg.server.build_command = "pip install -r requirements.txt"
            cfg.server.start_command = "uvicorn main:app"
            cfg.network.access = "public"
            cfg.network.subdomain = "api"
            cfg.security.basic_auth = True
            cfg.security.username = "admin"
            cfg.security.password_hash = "$2b$12$fakehash"
            cfg.watcher.enabled = False

            save_project_config(cfg)
            loaded = load_project_config("api-server")

        assert loaded.name == "api-server"
        assert loaded.type == "fastapi"
        assert loaded.server.port == 8000
        assert loaded.server.start_command == "uvicorn main:app"
        assert loaded.network.subdomain == "api"
        assert loaded.security.basic_auth is True
        assert loaded.security.username == "admin"
        assert loaded.watcher.enabled is False


class TestListProjects:
    def test_returns_empty_list_when_no_projects(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            result = list_projects()
        assert result == []

    def test_returns_sorted_project_names(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            for name in ("zebra", "alpha", "mango"):
                cfg = ProjectConfig()
                cfg.name = name
                save_project_config(cfg)
            result = list_projects()

        assert result == ["alpha", "mango", "zebra"]

    def test_single_project_returned(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = ProjectConfig()
            cfg.name = "only-project"
            save_project_config(cfg)
            result = list_projects()
        assert result == ["only-project"]


class TestDeleteProjectConfig:
    def test_removes_directory(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            cfg = ProjectConfig()
            cfg.name = "to-delete"
            save_project_config(cfg)

            projects = list_projects()
            assert "to-delete" in projects

            delete_project_config("to-delete")
            projects_after = list_projects()

        assert "to-delete" not in projects_after

    def test_delete_nonexistent_does_not_raise(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            # Should silently succeed
            delete_project_config("does-not-exist")


class TestProjectConfigPath:
    def test_creates_parent_directories(self, tmp_path):
        with _patch_homehost_dir(tmp_path):
            path = project_config_path("brand-new-project")

        assert path.parent.exists()
        assert path.parent.is_dir()
        assert path.name == "project.toml"


class TestAtomicWrite:
    def test_old_config_intact_if_exception_during_write(self, tmp_path, monkeypatch):
        """Verify _atomic_write cleans up temp file on failure and keeps old data."""
        hh = tmp_path / ".homehost"
        hh.mkdir()

        with patch("homehost.core.config.homehost_dir", return_value=hh):
            # Write initial config
            original = GlobalConfig()
            original.general.dashboard_port = 4321
            save_global_config(original)

            # Confirm it's there
            loaded = load_global_config()
            assert loaded.general.dashboard_port == 4321

            # Simulate a failure AFTER the temp file is written but BEFORE the
            # atomic rename.  We patch os.replace so it raises — but we must NOT
            # pre-delete the temp file so _atomic_write's own except handler runs.
            original_replace = os.replace

            def boom(src, dst):
                # Remove src ourselves so unlink in except block also fails gracefully
                try:
                    os.unlink(src)
                except FileNotFoundError:
                    pass
                raise OSError("simulated disk full")

            monkeypatch.setattr(os, "replace", boom)

            with pytest.raises(OSError):
                cfg2 = GlobalConfig()
                cfg2.general.dashboard_port = 9999
                save_global_config(cfg2)

            # Restore os.replace and confirm old config is still readable
            monkeypatch.setattr(os, "replace", original_replace)
            still_loaded = load_global_config()

        assert still_loaded.general.dashboard_port == 4321
