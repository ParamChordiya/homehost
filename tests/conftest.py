"""Shared pytest fixtures for HomeHost test suite."""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch


@pytest.fixture
def temp_dir():
    """Temporary directory that's cleaned up after the test."""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def mock_homehost_dir(temp_dir, monkeypatch):
    """Patch ~/.homehost to a temp directory."""
    hh_dir = temp_dir / ".homehost"
    hh_dir.mkdir()

    # Patch both the module-level function and where it's imported
    monkeypatch.setattr("homehost.core.config.homehost_dir", lambda: hh_dir)
    return hh_dir


@pytest.fixture
def static_project_dir(temp_dir):
    """A minimal static HTML project directory."""
    (temp_dir / "index.html").write_text("<html><body>Hello</body></html>")
    (temp_dir / "styles.css").write_text("body { margin: 0; }")
    return temp_dir


@pytest.fixture
def flask_project_dir(temp_dir):
    """A minimal Flask project directory."""
    (temp_dir / "app.py").write_text(
        "from flask import Flask\napp = Flask(__name__)\n@app.route('/')\ndef index(): return 'Hello'\n"
    )
    (temp_dir / "requirements.txt").write_text("flask>=3.0.0\n")
    return temp_dir


@pytest.fixture
def nextjs_project_dir(temp_dir):
    """A minimal Next.js project directory."""
    pkg = '{"name":"my-app","dependencies":{"next":"14.0.0","react":"18.0.0"}}'
    (temp_dir / "package.json").write_text(pkg)
    return temp_dir


@pytest.fixture
def mock_process_manager():
    """A mock ProcessManager that doesn't actually spawn processes."""
    manager = MagicMock()
    manager.is_running.return_value = False
    manager.status.return_value = "stopped"
    return manager


@pytest.fixture
def sample_global_config():
    from homehost.core.config import GlobalConfig

    return GlobalConfig()


@pytest.fixture
def sample_project_config():
    from homehost.core.config import ProjectConfig

    cfg = ProjectConfig()
    cfg.name = "test-project"
    cfg.type = "static"
    cfg.path = "/tmp/test-project"
    return cfg
