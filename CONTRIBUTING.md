# Contributing to HomeHost

Thank you for your interest in contributing to HomeHost. This guide will walk you through everything you need to get a working development environment, understand the codebase, and submit high-quality contributions.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [Code Style](#code-style)
- [Commit Convention](#commit-convention)
- [Pull Request Process](#pull-request-process)
- [Architecture Overview](#architecture-overview)
- [How to Add a New Project Type](#how-to-add-a-new-project-type)
- [How to Add a New Starter Template](#how-to-add-a-new-starter-template)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)

---

## Code of Conduct

HomeHost is committed to a welcoming and inclusive community. We expect contributors to:

- Be respectful and constructive in all interactions
- Welcome newcomers and help them get oriented
- Assume good faith in code reviews and discussions
- Focus criticism on code and ideas, never on people

Persistent violations may result in removal from the project.

---

## Development Setup

### Prerequisites

- Python 3.10, 3.11, or 3.12
- Git
- A working install of `pip` (or `pipx`)

### Clone and install

```bash
# Fork the repo on GitHub first, then:
git clone https://github.com/<your-username>/homehost.git
cd homehost

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# Install in editable mode with all dev dependencies
pip install -e ".[dev]"

# Verify the install
homehost --version
```

The `-e` flag installs the package in editable mode, so changes to `homehost/` are reflected immediately without reinstalling.

### Environment variables

Copy `.env.example` to `.env` (if one exists) and fill in any required values. For most development work, no environment variables are needed.

---

## Running Tests

HomeHost uses [pytest](https://pytest.org/) with `pytest-asyncio` for async test support.

```bash
# Run the full test suite
pytest

# Run with verbose output
pytest -v

# Run a specific test file
pytest tests/unit/test_detector.py

# Run a specific test by name
pytest -k "test_detects_flask_project"

# Run only unit tests (fast)
pytest tests/unit/

# Run integration tests (requires Caddy installed)
pytest tests/integration/

# Run with coverage report
pytest --cov=homehost --cov-report=html
open htmlcov/index.html   # macOS
```

The CI pipeline requires **85% coverage**. If your changes reduce coverage, add tests to compensate.

### Test structure

```
tests/
├── unit/           # Pure Python tests, no I/O, no subprocesses
├── integration/    # Tests that start Caddy or other real services
├── e2e/            # End-to-end tests that exercise the full stack
└── conftest.py     # Shared fixtures (tmp dirs, mock projects, etc.)
```

---

## Code Style

HomeHost enforces consistent style using three tools that run in CI:

### ruff (linting)

```bash
ruff check homehost/          # Check for issues
ruff check homehost/ --fix    # Auto-fix what's possible
```

### black (formatting)

```bash
black homehost/               # Format all files
black homehost/ --check       # Dry-run (exits non-zero if changes needed)
```

### mypy (type checking)

```bash
mypy homehost/
```

All three must pass cleanly before a PR can merge. Run them together:

```bash
ruff check homehost/ && black homehost/ --check && mypy homehost/
```

Or fix and format in one pass:

```bash
ruff check homehost/ --fix && black homehost/
```

### Style conventions

- **Type annotations are mandatory** on all public functions and methods. Private helpers should be annotated too where it aids clarity.
- **Docstrings** on all public classes, methods, and functions. Use Google-style docstrings.
- **No magic numbers** — use named constants or config values.
- **Async by default** for I/O operations (subprocess management, file watching, network calls).
- **`structlog`** for all logging — never `print()` in library code.

---

## Commit Convention

HomeHost uses [Conventional Commits](https://www.conventionalcommits.org/). Every commit message must follow this format:

```
<type>(<scope>): <short description>

[optional body]

[optional footer(s)]
```

### Types

| Type | When to use |
|---|---|
| `feat` | A new feature visible to users |
| `fix` | A bug fix |
| `docs` | Documentation changes only |
| `style` | Formatting, whitespace (no logic change) |
| `refactor` | Code restructuring with no behavior change |
| `perf` | Performance improvements |
| `test` | Adding or fixing tests |
| `build` | Build system or dependency changes |
| `ci` | CI configuration changes |
| `chore` | Maintenance tasks (release, cleanup) |

### Scopes (optional but encouraged)

`tui`, `core`, `servers`, `network`, `security`, `dashboard`, `cli`, `docs`, `deps`

### Examples

```
feat(tui): add QR code to tunnel status screen
fix(servers): restart Flask server after ImportError on reload
docs(quickstart): add Django walkthrough section
test(detector): cover edge case where package.json has no dependencies
chore(release): v0.2.0
```

Breaking changes must include `BREAKING CHANGE:` in the commit footer:

```
feat(config)!: rename `port` to `local_port` in homehost.toml

BREAKING CHANGE: projects using `port` in homehost.toml must rename the key to `local_port`.
```

---

## Pull Request Process

1. **Open an issue first** for any significant change (new feature, architecture change, major refactor). For small bug fixes and documentation improvements, a PR without a prior issue is fine.

2. **Branch naming**: use `feat/`, `fix/`, `docs/`, or `chore/` prefixes.
   ```bash
   git checkout -b feat/django-support
   git checkout -b fix/caddy-restart-race-condition
   ```

3. **Keep PRs focused**: one logical change per PR. If you find yourself touching many unrelated files, split into multiple PRs.

4. **Write tests**: new features need unit tests. Bug fixes should include a test that would have caught the bug.

5. **Update documentation**: if your change affects user-facing behavior, update the relevant `docs/` file and the README if needed.

6. **Fill in the PR template**: describe what changed, why, and how to test it manually.

7. **CI must be green**: all tests, linting, and type checks must pass.

8. **Expect review feedback**: maintainers will leave comments. Respond to each one — either implement the suggestion or explain why you disagree. Reviews are a conversation.

9. **Squash before merge**: we prefer a clean commit history. Before your PR is merged, you may be asked to squash commits or the maintainer will squash on merge.

---

## Architecture Overview

Understanding the module layout helps you find the right place for your change.

```
homehost/
├── cli.py              # Typer CLI entrypoint — command definitions only
├── core/
│   ├── config.py       # Global and project config loading/saving (TOML)
│   ├── detector.py     # Auto-detects project type from directory contents
│   ├── process.py      # Subprocess lifecycle (start, stop, restart, health)
│   └── project.py      # Project data model — the central state object
├── servers/
│   ├── caddy.py        # Generates Caddyfile configs and manages the Caddy process
│   ├── installer.py    # Downloads and installs Caddy and cloudflared binaries
│   ├── reverse_proxy.py# Caddy reverse-proxy config helpers
│   └── static.py       # Caddy static file server config helpers
├── network/
│   ├── tunnel.py       # Manages the cloudflared tunnel process
│   ├── local.py        # Local network discovery (LAN IP detection)
│   ├── dns.py          # DNS utilities
│   ├── ssl.py          # TLS/certificate helpers (for future local HTTPS)
│   └── firewall.py     # Platform firewall checks
├── security/
│   ├── hardening.py    # Injects security headers and rate-limit config into Caddy
│   └── secrets.py      # Password hashing (bcrypt) for basic auth
├── tui/
│   ├── app.py          # Textual application — root TUI app
│   └── screens/        # Textual Screen subclasses (setup wizard, main dashboard)
│   └── widgets/        # Reusable Textual widgets (log panel, status bar, QR)
├── dashboard/
│   ├── api.py          # FastAPI router — REST API backing the web dashboard
│   └── server.py       # Uvicorn server wrapper for the dashboard
├── deploy/             # (Future) one-click deploy helpers
└── utils/
    ├── logger.py       # structlog configuration
    ├── network.py      # Port availability, URL helpers
    ├── platform.py     # OS detection, path helpers
    └── updater.py      # Self-update logic
```

### Key data flow

1. User runs `homehost serve ./my-app`
2. `cli.py` parses args and creates a `Project` object (`core/project.py`)
3. `core/detector.py` identifies the project type
4. `servers/caddy.py` generates a `Caddyfile` for the project
5. `core/process.py` launches Caddy and the app server as subprocesses
6. `network/tunnel.py` optionally starts cloudflared
7. `tui/app.py` takes over the terminal, streaming logs and status
8. `dashboard/server.py` starts a background FastAPI server on port 9111

---

## How to Add a New Project Type

A "project type" tells HomeHost how to detect and run a specific kind of web app. Adding one requires changes in three places:

### 1. Add the type enum

In `homehost/core/project.py`, add your type to the `ProjectType` enum:

```python
class ProjectType(str, Enum):
    STATIC = "static"
    FLASK = "flask"
    FASTAPI = "fastapi"
    DJANGO = "django"
    NEXTJS = "nextjs"
    REACT = "react"
    EXPRESS = "express"
    NODE = "node"
    YOUR_TYPE = "your_type"   # <-- add here
    UNKNOWN = "unknown"
```

### 2. Add detection logic

In `homehost/core/detector.py`, add a detection method to the `ProjectDetector` class:

```python
def _detect_your_type(self, path: Path) -> bool:
    """Return True if the project at `path` is a YourType project."""
    # Example: check for a config file
    if (path / "your_config.yaml").exists():
        return True
    # Example: check package.json for a dependency
    pkg = self._read_package_json(path)
    if pkg and "your-framework" in pkg.get("dependencies", {}):
        return True
    return False
```

Then register it in `detect()` — order matters, more specific checks should come first:

```python
def detect(self, path: Path) -> ProjectType:
    if self._detect_your_type(path):
        return ProjectType.YOUR_TYPE
    # ... existing checks ...
```

### 3. Add server configuration

In `homehost/servers/caddy.py`, add a case to `build_caddyfile()` that generates the right Caddy config for your type. This is typically either a `reverse_proxy` directive (for app servers) or a `file_server` directive (for static output).

```python
elif project.type == ProjectType.YOUR_TYPE:
    return self._build_reverse_proxy_config(
        host=host,
        port=project.port or 4321,
        start_command="your-framework serve",
    )
```

### 4. Add tests

Add a test file `tests/unit/test_detector_your_type.py` covering:
- Detection when all signals are present
- Detection when only some signals are present (partial matches)
- Non-detection when signals are absent

### 5. Update documentation

- Add a row to the **Supported Project Types** table in `README.md`
- Update `docs/quickstart.md` with a "Your First YourType App" section if it's a common framework

---

## How to Add a New Starter Template

Templates live in `templates/<name>/`. Each template is a directory of files that gets copied to the user's chosen destination when they run `homehost new <template> <name>`.

### Template structure

```
templates/
└── my-framework/
    ├── .homehost-template.toml    # Template metadata
    ├── homehost.toml              # Project config for this template
    ├── README.md                  # Project-specific README
    └── <framework files>          # The actual starter code
```

### `.homehost-template.toml` format

```toml
[template]
name = "my-framework"
description = "A minimal My Framework starter with HomeHost integration"
type = "my_type"                   # Must match a ProjectType value
requires = ["my-framework>=2.0"]   # pip/npm packages needed at runtime
homepage = "https://myframework.dev"
```

### Variable substitution

Use `{{project_name}}` in any template file — HomeHost will replace it with the name the user provides.

```html
<!-- templates/my-framework/index.html -->
<title>{{project_name}}</title>
```

### Testing your template

```bash
homehost new my-framework test-project
cd test-project
homehost serve .
```

Verify that HomeHost detects the type correctly, starts the server, and the site loads in a browser.

---

## Reporting Bugs

Open an issue at [github.com/ParamChordiya/homehost/issues](https://github.com/ParamChordiya/homehost/issues) and use the **Bug Report** template. Please include:

- HomeHost version (`homehost version`)
- OS and Python version
- The exact command you ran
- The full output including any error messages or tracebacks
- The output of `homehost doctor`

---

## Requesting Features

Open an issue using the **Feature Request** template. Describe:

- The problem you're trying to solve (not just the solution you have in mind)
- How you currently work around the limitation
- Any prior art — does another tool handle this well?

Feature requests with clear use cases and prior art are much more likely to be implemented quickly.
