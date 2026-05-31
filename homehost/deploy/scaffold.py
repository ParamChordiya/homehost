"""Starter project template scaffolding for HomeHost."""

from __future__ import annotations

import shutil
from enum import Enum
from pathlib import Path


class TemplateType(str, Enum):
    STATIC = "static"
    FLASK = "flask"
    FASTAPI = "fastapi"
    NEXTJS = "nextjs"
    REACT = "react"


_TEMPLATE_DIR_MAP: dict[TemplateType, str] = {
    TemplateType.STATIC: "static-html",
    TemplateType.FLASK: "flask-app",
    TemplateType.FASTAPI: "fastapi-app",
    TemplateType.NEXTJS: "nextjs-app",
    TemplateType.REACT: "react-app",
}

_TEMPLATE_META: dict[TemplateType, dict[str, object]] = {
    TemplateType.STATIC: {
        "description": "Plain HTML/CSS/JS landing page — no build step required.",
        "files": ["index.html", "styles.css", "script.js"],
    },
    TemplateType.FLASK: {
        "description": "Python Flask web application with Jinja2 templates.",
        "files": ["app.py", "requirements.txt", "templates/index.html"],
    },
    TemplateType.FASTAPI: {
        "description": "FastAPI REST service with Pydantic models and async endpoints.",
        "files": ["main.py", "requirements.txt"],
    },
    TemplateType.NEXTJS: {
        "description": "Next.js React application (requires Node.js).",
        "files": ["package.json", "pages/index.js"],
    },
    TemplateType.REACT: {
        "description": "Create React App starter (requires Node.js).",
        "files": ["package.json", "src/App.jsx", "public/index.html"],
    },
}


def get_template_dir(template: TemplateType) -> Path:
    """Return the absolute path to the named template inside the homehost package."""
    # The templates/ directory lives at the repository / package root, one
    # level above the homehost/ Python package directory.
    package_root = Path(__file__).parent.parent.parent
    subdir = _TEMPLATE_DIR_MAP[template]
    return package_root / "templates" / subdir


def scaffold_project(
    template: TemplateType,
    target_dir: Path,
    project_name: str,
) -> list[Path]:
    """Copy a starter template into *target_dir* and return created file paths.

    *target_dir* is created if it does not already exist.  Existing files are
    **not** overwritten so it is safe to call on a partially-initialised
    directory.

    Raises ``FileNotFoundError`` if the requested template is not installed.
    """
    src = get_template_dir(template)
    if not src.exists():
        raise FileNotFoundError(
            f"Template '{template.value}' not found at {src}. " "Ensure the homehost package was installed correctly."
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []

    for src_file in src.rglob("*"):
        if src_file.is_dir():
            continue

        relative = src_file.relative_to(src)
        dest_file = target_dir / relative
        dest_file.parent.mkdir(parents=True, exist_ok=True)

        if dest_file.exists():
            # Don't clobber user modifications
            continue

        # Perform simple substitution of the placeholder project name
        try:
            text = src_file.read_text(encoding="utf-8")
            text = text.replace("{{project_name}}", project_name).replace("{{ project_name }}", project_name)
            dest_file.write_text(text, encoding="utf-8")
        except UnicodeDecodeError:
            # Binary file — copy verbatim
            shutil.copy2(src_file, dest_file)

        created.append(dest_file)

    return created


def list_templates() -> list[dict[str, object]]:
    """Return metadata for all available templates.

    Each entry contains:
    - ``name``        — display name
    - ``type``        — ``TemplateType`` value string
    - ``description`` — one-line description
    - ``files``       — representative list of files in the template
    - ``available``   — whether the template directory exists on disk
    """
    results: list[dict[str, object]] = []
    for t in TemplateType:
        meta = dict(_TEMPLATE_META.get(t, {}))
        tdir = get_template_dir(t)
        results.append(
            {
                "name": _TEMPLATE_DIR_MAP[t].replace("-", " ").title(),
                "type": t.value,
                "description": meta.get("description", ""),
                "files": list(meta.get("files") or []),  # type: ignore[call-overload]
                "available": tdir.exists(),
            }
        )
    return results
