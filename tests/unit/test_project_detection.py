"""Unit tests for homehost.core.project — project type detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from homehost.core.project import (
    DetectionResult,
    ProjectType,
    detect_project_type,
    validate_project_directory,
)

# ── helpers ────────────────────────────────────────────────────────────────────


def write_pkg(directory: Path, deps: dict, dev_deps: dict | None = None) -> None:
    """Write a package.json with the given dependency dicts."""
    pkg: dict = {"name": "test-app", "version": "1.0.0", "dependencies": deps}
    if dev_deps:
        pkg["devDependencies"] = dev_deps
    (directory / "package.json").write_text(json.dumps(pkg))


def write_requirements(directory: Path, packages: list[str]) -> None:
    """Write a requirements.txt listing each package."""
    (directory / "requirements.txt").write_text("\n".join(packages) + "\n")


# ── Static HTML ────────────────────────────────────────────────────────────────


class TestStaticDetection:
    def test_index_html_detected_as_static(self, temp_dir):
        (temp_dir / "index.html").write_text("<html/>")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.STATIC
        assert result.confidence == "certain"

    def test_other_html_file_detected_as_static_probable(self, temp_dir):
        (temp_dir / "about.html").write_text("<html/>")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.STATIC
        assert result.confidence == "probable"


# ── Python frameworks ──────────────────────────────────────────────────────────


class TestFlaskDetection:
    def test_requirements_with_flask(self, temp_dir):
        write_requirements(temp_dir, ["flask>=3.0.0"])
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.FLASK
        assert result.confidence == "certain"

    def test_flask_with_version_pin(self, temp_dir):
        write_requirements(temp_dir, ["Flask==3.0.3"])
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.FLASK

    def test_flask_via_import_in_source(self, temp_dir):
        (temp_dir / "requirements.txt").write_text("# no framework listed\n")
        (temp_dir / "app.py").write_text("from flask import Flask\napp = Flask(__name__)\n")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.FLASK
        assert result.confidence == "probable"


class TestFastAPIDetection:
    def test_requirements_with_fastapi(self, temp_dir):
        write_requirements(temp_dir, ["fastapi>=0.111.0", "uvicorn"])
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.FASTAPI
        assert result.confidence == "certain"


class TestDjangoDetection:
    def test_requirements_with_django(self, temp_dir):
        write_requirements(temp_dir, ["Django>=4.2.0"])
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.DJANGO
        assert result.confidence == "certain"

    def test_django_beats_flask_when_both_listed(self, temp_dir):
        """Django is checked first, so it wins if both appear."""
        write_requirements(temp_dir, ["Django>=4.2", "flask>=3.0"])
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.DJANGO


# ── Node.js frameworks ─────────────────────────────────────────────────────────


class TestNextjsDetection:
    def test_package_json_with_next_dep(self, temp_dir):
        write_pkg(temp_dir, {"next": "14.0.0", "react": "18.0.0"})
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.NEXTJS
        assert result.confidence == "certain"
        assert result.framework_version == "14.0.0"

    def test_next_in_dev_deps(self, temp_dir):
        write_pkg(temp_dir, {}, dev_deps={"next": "14.2.0"})
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.NEXTJS


class TestReactDetection:
    def test_react_scripts_detected_as_react_cra(self, temp_dir):
        write_pkg(temp_dir, {"react": "18.0.0", "react-scripts": "5.0.1"})
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.REACT
        assert result.confidence == "certain"
        assert "CRA" in result.reason

    def test_vite_plus_react_detected_as_react_vite(self, temp_dir):
        write_pkg(temp_dir, {"react": "18.0.0"}, dev_deps={"vite": "5.0.0"})
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.REACT
        assert "Vite" in result.reason


class TestGenericNodeDetection:
    def test_package_json_without_framework_is_node(self, temp_dir):
        write_pkg(temp_dir, {"express": "4.18.0"})
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.NODE
        assert result.confidence == "probable"

    def test_empty_package_json_is_node(self, temp_dir):
        (temp_dir / "package.json").write_text('{"name":"my-app"}')
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.NODE


# ── Docker ─────────────────────────────────────────────────────────────────────


class TestDockerDetection:
    def test_dockerfile_only(self, temp_dir):
        (temp_dir / "Dockerfile").write_text("FROM python:3.12\n")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.DOCKER
        assert result.confidence == "certain"

    def test_docker_compose_only(self, temp_dir):
        (temp_dir / "docker-compose.yml").write_text("version: '3'\n")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.DOCKER


# ── Fallback / Custom ──────────────────────────────────────────────────────────


class TestFallbackDetection:
    def test_empty_directory_returns_custom_guessed(self, temp_dir):
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.CUSTOM
        assert result.confidence == "guessed"

    def test_non_existent_directory_returns_custom(self, temp_dir):
        missing = temp_dir / "does-not-exist"
        result = detect_project_type(missing)
        assert result.project_type == ProjectType.CUSTOM
        assert "does not exist" in result.reason.lower() or result.confidence == "guessed"


# ── Priority order ─────────────────────────────────────────────────────────────


class TestPriorityOrder:
    def test_node_beats_python_when_both_present(self, temp_dir):
        """package.json is checked before requirements.txt."""
        write_pkg(temp_dir, {"next": "14.0.0"})
        write_requirements(temp_dir, ["flask>=3.0"])
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.NEXTJS

    def test_python_beats_static_when_both_present(self, temp_dir):
        """Python markers take priority over index.html."""
        write_requirements(temp_dir, ["fastapi>=0.111"])
        (temp_dir / "index.html").write_text("<html/>")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.FASTAPI

    def test_static_beats_docker_when_both_present(self, temp_dir):
        """index.html check happens before Dockerfile check."""
        (temp_dir / "index.html").write_text("<html/>")
        (temp_dir / "Dockerfile").write_text("FROM nginx\n")
        result = detect_project_type(temp_dir)
        assert result.project_type == ProjectType.STATIC


# ── validate_project_directory ─────────────────────────────────────────────────


class TestValidateProjectDirectory:
    def test_valid_directory_returns_true(self, temp_dir):
        ok, msg = validate_project_directory(temp_dir)
        assert ok is True
        assert msg == ""

    def test_non_existent_directory_returns_false(self, temp_dir):
        missing = temp_dir / "no-such-dir"
        ok, msg = validate_project_directory(missing)
        assert ok is False
        assert "does not exist" in msg.lower()

    def test_file_path_returns_false(self, temp_dir):
        f = temp_dir / "somefile.txt"
        f.write_text("hello")
        ok, msg = validate_project_directory(f)
        assert ok is False
        assert "not a directory" in msg.lower()

    def test_permission_denied_returns_false(self, temp_dir):
        """Simulate unreadable directory (Unix only — skipped on Windows)."""
        import platform

        if platform.system() == "Windows":
            pytest.skip("chmod not reliable on Windows")

        protected = temp_dir / "protected"
        protected.mkdir(mode=0o000)
        try:
            ok, msg = validate_project_directory(protected)
            assert ok is False
            assert "permission" in msg.lower()
        finally:
            protected.chmod(0o700)


# ── ProjectType properties ─────────────────────────────────────────────────────


class TestProjectTypeProperties:
    def test_all_types_have_a_label(self):
        for pt in ProjectType:
            assert isinstance(pt.label, str)
            assert len(pt.label) > 0

    def test_all_types_have_default_port(self):
        for pt in ProjectType:
            assert isinstance(pt.default_port, int)
            assert pt.default_port > 0

    def test_needs_node_correct(self):
        assert ProjectType.NEXTJS.needs_node is True
        assert ProjectType.REACT.needs_node is True
        assert ProjectType.NODE.needs_node is True
        assert ProjectType.FLASK.needs_node is False
        assert ProjectType.STATIC.needs_node is False

    def test_needs_python_correct(self):
        assert ProjectType.FLASK.needs_python is True
        assert ProjectType.FASTAPI.needs_python is True
        assert ProjectType.DJANGO.needs_python is True
        assert ProjectType.NEXTJS.needs_python is False
        assert ProjectType.STATIC.needs_python is False
