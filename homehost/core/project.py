"""Project type detection, registration, and scaffolding dispatch."""

from __future__ import annotations

import json
import sys
from enum import Enum
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class ProjectType(str, Enum):
    STATIC = "static"
    FLASK = "flask"
    FASTAPI = "fastapi"
    DJANGO = "django"
    NEXTJS = "nextjs"
    REACT = "react"
    NODE = "node"
    DOCKER = "docker"
    CUSTOM = "custom"

    @property
    def label(self) -> str:
        labels = {
            "static": "Static HTML/CSS/JS",
            "flask": "Python · Flask",
            "fastapi": "Python · FastAPI",
            "django": "Python · Django",
            "nextjs": "Next.js",
            "react": "React (Vite/CRA)",
            "node": "Node.js",
            "docker": "Docker",
            "custom": "Custom",
        }
        return labels[self.value]

    @property
    def default_port(self) -> int:
        ports = {
            "static": 8080,
            "flask": 5000,
            "fastapi": 8000,
            "django": 8000,
            "nextjs": 3000,
            "react": 5173,
            "node": 3000,
            "docker": 8080,
            "custom": 8080,
        }
        return ports[self.value]

    @property
    def default_start_command(self) -> str:
        cmds = {
            "static": "",
            "flask": "gunicorn app:app",
            "fastapi": "uvicorn main:app --host 0.0.0.0",
            "django": "gunicorn myproject.wsgi",
            "nextjs": "npx next start",
            "react": "npx serve dist",
            "node": "npm start",
            "docker": "",
            "custom": "",
        }
        return cmds[self.value]

    @property
    def default_build_command(self) -> str:
        cmds = {
            "static": "",
            "flask": "",
            "fastapi": "",
            "django": "python manage.py collectstatic --noinput",
            "nextjs": "npx next build",
            "react": "npm run build",
            "node": "npm run build",
            "docker": "docker build -t app .",
            "custom": "",
        }
        return cmds[self.value]

    @property
    def needs_node(self) -> bool:
        return self in (ProjectType.NEXTJS, ProjectType.REACT, ProjectType.NODE)

    @property
    def needs_python(self) -> bool:
        return self in (ProjectType.FLASK, ProjectType.FASTAPI, ProjectType.DJANGO)


class DetectionResult(NamedTuple):
    project_type: ProjectType
    confidence: str  # "certain" | "probable" | "guessed"
    reason: str
    framework_version: str


def detect_project_type(directory: Path) -> DetectionResult:
    """Auto-detect project type from directory contents.

    Priority order matches the spec:
    1. package.json → Node variants
    2. Python project files → Python variants
    3. index.html → Static
    4. Dockerfile → Docker
    5. Unknown → Custom
    """
    if not directory.exists():
        return DetectionResult(ProjectType.CUSTOM, "guessed", "Directory does not exist", "")

    # ── Node.js detection ──────────────────────────────────────────────────────
    pkg_json = directory / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pkg = {}

        all_deps: dict[str, str] = {}
        all_deps.update(pkg.get("dependencies", {}))
        all_deps.update(pkg.get("devDependencies", {}))

        if "next" in all_deps:
            ver = all_deps.get("next", "")
            return DetectionResult(ProjectType.NEXTJS, "certain", "Found 'next' in package.json", ver)

        if "react-scripts" in all_deps:
            ver = all_deps.get("react-scripts", "")
            return DetectionResult(ProjectType.REACT, "certain", "Found 'react-scripts' (CRA)", ver)

        if "vite" in all_deps and "react" in all_deps:
            ver = all_deps.get("vite", "")
            return DetectionResult(ProjectType.REACT, "certain", "Found Vite + React", ver)

        # generic Node
        name = pkg.get("name", "")
        return DetectionResult(ProjectType.NODE, "probable", f"Found package.json ('{name}')", pkg.get("version", ""))

    # ── Python detection ───────────────────────────────────────────────────────
    python_markers = [
        directory / "requirements.txt",
        directory / "Pipfile",
        directory / "pyproject.toml",
        directory / "setup.py",
        directory / "setup.cfg",
    ]
    if any(m.exists() for m in python_markers):
        deps = _collect_python_deps(directory)

        if "django" in deps:
            return DetectionResult(
                ProjectType.DJANGO, "certain", "Found 'django' in dependencies", deps.get("django", "")
            )
        if "fastapi" in deps:
            return DetectionResult(
                ProjectType.FASTAPI, "certain", "Found 'fastapi' in dependencies", deps.get("fastapi", "")
            )
        if "flask" in deps:
            return DetectionResult(ProjectType.FLASK, "certain", "Found 'flask' in dependencies", deps.get("flask", ""))

        # Check source files for imports
        if _any_file_imports(directory, "django"):
            return DetectionResult(ProjectType.DJANGO, "probable", "Detected Django imports in source", "")
        if _any_file_imports(directory, "fastapi"):
            return DetectionResult(ProjectType.FASTAPI, "probable", "Detected FastAPI imports in source", "")
        if _any_file_imports(directory, "flask"):
            return DetectionResult(ProjectType.FLASK, "probable", "Detected Flask imports in source", "")

        return DetectionResult(ProjectType.CUSTOM, "probable", "Python project — framework unknown", "")

    # ── Static site detection ──────────────────────────────────────────────────
    if (directory / "index.html").exists():
        return DetectionResult(ProjectType.STATIC, "certain", "Found index.html", "")

    # ── Docker ────────────────────────────────────────────────────────────────
    if (directory / "Dockerfile").exists() or (directory / "docker-compose.yml").exists():
        return DetectionResult(ProjectType.DOCKER, "certain", "Found Dockerfile / docker-compose.yml", "")

    # ── Fallback ───────────────────────────────────────────────────────────────
    html_files = list(directory.glob("*.html"))
    if html_files:
        return DetectionResult(ProjectType.STATIC, "probable", f"Found {len(html_files)} HTML file(s)", "")

    return DetectionResult(ProjectType.CUSTOM, "guessed", "No recognizable project markers found", "")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _collect_python_deps(directory: Path) -> dict[str, str]:
    """Extract package names from common Python dependency files."""
    deps: dict[str, str] = {}

    req = directory / "requirements.txt"
    if req.exists():
        for line in req.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip().split("#")[0].strip()
            if not line or line.startswith("-"):
                continue
            for sep in (">=", "<=", "==", "!=", "~=", ">", "<", "["):
                if sep in line:
                    name = line.split(sep)[0].strip().lower()
                    deps[name] = line
                    break
            else:
                deps[line.lower()] = line

    ppt = directory / "pyproject.toml"
    if ppt.exists():
        try:
            data = tomllib.loads(ppt.read_text(encoding="utf-8"))
            for dep in data.get("project", {}).get("dependencies", []):
                name = dep.split()[0].split(">=")[0].split("==")[0].lower().rstrip(";")
                deps[name] = dep
        except Exception:
            pass

    return deps


def _any_file_imports(directory: Path, package: str) -> bool:
    """Return True if any .py file in the directory imports `package`."""
    for py_file in list(directory.glob("*.py"))[:20]:  # cap scan depth
        try:
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            if f"import {package}" in text or f"from {package}" in text:
                return True
        except OSError:
            pass
    return False


def validate_project_directory(directory: Path) -> tuple[bool, str]:
    """Check that a directory is usable as a project root.

    Returns (ok, error_message).
    """
    if not directory.exists():
        return False, f"Directory does not exist: {directory}"
    if not directory.is_dir():
        return False, f"Path is not a directory: {directory}"
    try:
        # Check readable
        list(directory.iterdir())
    except PermissionError:
        return False, f"Permission denied reading directory: {directory}"
    return True, ""
