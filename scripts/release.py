#!/usr/bin/env python3
"""HomeHost release script.

Automates the full release process: version bump, changelog update,
git tag, PyPI upload.

Usage:
    python scripts/release.py <version>

Examples:
    python scripts/release.py 0.2.0
    python scripts/release.py 1.0.0-rc1   # dry-run only, won't push

Steps:
    1. Validate version format (semver)
    2. Check git working tree is clean (no uncommitted changes)
    3. Confirm the release with the user
    4. Update version in homehost/__init__.py
    5. Update version in pyproject.toml
    6. Update CHANGELOG.md (move [Unreleased] to [version] - [date])
    7. Commit: "chore(release): v{version}"
    8. Tag: git tag -a v{version} -m "Release v{version}"
    9. Push commit and tag to origin
    10. Build: python -m build
    11. Upload to PyPI: twine upload dist/*
    12. Print success message with PyPI URL
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
INIT_FILE = REPO_ROOT / "homehost" / "__init__.py"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
DIST_DIR = REPO_ROOT / "dist"

SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"\.(?P<minor>0|[1-9]\d*)"
    r"\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def run(cmd: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a shell command, optionally capturing output."""
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=check,
        cwd=REPO_ROOT,
    )


def die(message: str) -> None:
    """Print an error message and exit with code 1."""
    print(f"\n  ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def confirm(prompt: str) -> bool:
    """Prompt the user for a yes/no confirmation."""
    while True:
        answer = input(f"{prompt} [y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False


def section(title: str) -> None:
    """Print a formatted section header."""
    width = 60
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")


# ---------------------------------------------------------------------------
# Step 1: Validate version
# ---------------------------------------------------------------------------


def validate_version(version: str) -> str:
    """Validate that the version string is valid semver.

    Args:
        version: Version string to validate (e.g. "0.2.0").

    Returns:
        The version string, unchanged.

    Raises:
        SystemExit: If the version string is not valid semver.
    """
    if not SEMVER_RE.match(version):
        die(
            f"'{version}' is not a valid semantic version.\n"
            "  Examples of valid versions: 0.2.0, 1.0.0, 2.1.3-rc1\n"
            "  See https://semver.org/"
        )
    return version


# ---------------------------------------------------------------------------
# Step 2: Check git state
# ---------------------------------------------------------------------------


def check_git_clean() -> None:
    """Ensure there are no uncommitted changes in the working tree.

    Raises:
        SystemExit: If there are staged or unstaged changes, or untracked files.
    """
    result = run(["git", "status", "--porcelain"], capture=True)
    if result.stdout.strip():
        die(
            "Working tree is not clean. Commit or stash your changes before releasing.\n\n"
            f"{result.stdout}"
        )


def check_on_main_branch() -> None:
    """Warn if not on the main branch."""
    result = run(["git", "branch", "--show-current"], capture=True)
    branch = result.stdout.strip()
    if branch not in ("main", "master"):
        print(f"\n  WARNING: You are on branch '{branch}', not 'main'.")
        if not confirm("  Continue anyway?"):
            sys.exit(0)


def check_tag_does_not_exist(version: str) -> None:
    """Ensure the tag for this version does not already exist.

    Args:
        version: The version to check (without the 'v' prefix).

    Raises:
        SystemExit: If the tag already exists.
    """
    result = run(["git", "tag", "--list", f"v{version}"], capture=True)
    if result.stdout.strip():
        die(f"Tag 'v{version}' already exists. Did you mean to release a different version?")


# ---------------------------------------------------------------------------
# Step 3: Get current version (for display)
# ---------------------------------------------------------------------------


def get_current_version() -> str:
    """Read the current version from homehost/__init__.py.

    Returns:
        The current version string.
    """
    content = INIT_FILE.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
    if not match:
        die(f"Could not find __version__ in {INIT_FILE}")
    return match.group(1)


# ---------------------------------------------------------------------------
# Step 4: Update __init__.py
# ---------------------------------------------------------------------------


def update_init_version(version: str) -> None:
    """Update __version__ in homehost/__init__.py.

    Args:
        version: The new version string.
    """
    content = INIT_FILE.read_text(encoding="utf-8")
    new_content = re.sub(
        r'^(__version__\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{version}"',
        content,
        flags=re.MULTILINE,
    )
    if new_content == content:
        die(f"Failed to update __version__ in {INIT_FILE} — pattern not found.")
    INIT_FILE.write_text(new_content, encoding="utf-8")
    print(f"  Updated {INIT_FILE.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Step 5: Update pyproject.toml
# ---------------------------------------------------------------------------


def update_pyproject_version(version: str) -> None:
    """Update the version field in pyproject.toml.

    Args:
        version: The new version string.
    """
    content = PYPROJECT_FILE.read_text(encoding="utf-8")
    # Only update the first occurrence (project version, not dependency constraints)
    new_content = re.sub(
        r'^(version\s*=\s*)["\'][^"\']+["\']',
        rf'\g<1>"{version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if new_content == content:
        die(f"Failed to update version in {PYPROJECT_FILE} — pattern not found.")
    PYPROJECT_FILE.write_text(new_content, encoding="utf-8")
    print(f"  Updated {PYPROJECT_FILE.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Step 6: Update CHANGELOG.md
# ---------------------------------------------------------------------------


def update_changelog(version: str) -> None:
    """Move the [Unreleased] section to [version] - [date] in CHANGELOG.md.

    Adds a new empty [Unreleased] section above the new version entry.

    Args:
        version: The new version string.

    Raises:
        SystemExit: If the [Unreleased] section is not found.
    """
    content = CHANGELOG_FILE.read_text(encoding="utf-8")
    today = date.today().isoformat()

    unreleased_pattern = re.compile(r"^## \[Unreleased\]$", re.MULTILINE)
    if not unreleased_pattern.search(content):
        die(f"'## [Unreleased]' section not found in {CHANGELOG_FILE}. Cannot update changelog.")

    # Replace the [Unreleased] header with a new [Unreleased] + versioned section
    new_header = f"## [Unreleased]\n\n## [{version}] - {today}"
    new_content = unreleased_pattern.sub(new_header, content, count=1)

    # Update the reference links at the bottom of the file
    github_base = "https://github.com/homehost-dev/homehost"
    previous_version = get_current_version()

    # Add a new comparison link for the new version
    new_link = f"[{version}]: {github_base}/compare/v{previous_version}...v{version}"
    unreleased_link_pattern = re.compile(
        rf"^\[Unreleased\]: {re.escape(github_base)}/compare/v.*\.\.\.HEAD$",
        re.MULTILINE,
    )
    new_unreleased_link = f"[Unreleased]: {github_base}/compare/v{version}...HEAD"

    if unreleased_link_pattern.search(new_content):
        new_content = unreleased_link_pattern.sub(
            f"{new_unreleased_link}\n{new_link}",
            new_content,
            count=1,
        )
    else:
        # Append links if they don't exist yet
        new_content = new_content.rstrip() + f"\n\n{new_unreleased_link}\n{new_link}\n"

    CHANGELOG_FILE.write_text(new_content, encoding="utf-8")
    print(f"  Updated {CHANGELOG_FILE.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# Step 7: Git commit
# ---------------------------------------------------------------------------


def git_commit(version: str) -> None:
    """Stage the modified files and create the release commit.

    Args:
        version: The version string used in the commit message.
    """
    run(["git", "add", str(INIT_FILE), str(PYPROJECT_FILE), str(CHANGELOG_FILE)])
    run(["git", "commit", "-m", f"chore(release): v{version}"])
    print(f"  Created commit: chore(release): v{version}")


# ---------------------------------------------------------------------------
# Step 8: Git tag
# ---------------------------------------------------------------------------


def git_tag(version: str) -> None:
    """Create an annotated git tag for the release.

    Args:
        version: The version string (tag will be v{version}).
    """
    run(["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"])
    print(f"  Created tag: v{version}")


# ---------------------------------------------------------------------------
# Step 9: Push
# ---------------------------------------------------------------------------


def git_push(version: str) -> None:
    """Push the commit and the tag to origin.

    Args:
        version: The version string (used to name the tag to push).
    """
    run(["git", "push", "origin", "HEAD"])
    run(["git", "push", "origin", f"v{version}"])
    print("  Pushed commit and tag to origin")


# ---------------------------------------------------------------------------
# Step 10: Build
# ---------------------------------------------------------------------------


def build_package() -> None:
    """Build the source distribution and wheel using python -m build.

    Cleans the dist/ directory first to avoid uploading stale artifacts.

    Raises:
        SystemExit: If the build fails.
    """
    # Clean old artifacts
    if DIST_DIR.exists():
        for artifact in DIST_DIR.iterdir():
            artifact.unlink()
        print(f"  Cleaned {DIST_DIR.relative_to(REPO_ROOT)}/")

    run([sys.executable, "-m", "build"])
    artifacts = list(DIST_DIR.iterdir())
    print(f"  Built {len(artifacts)} artifact(s):")
    for artifact in sorted(artifacts):
        print(f"    {artifact.name}")


# ---------------------------------------------------------------------------
# Step 11: Upload to PyPI
# ---------------------------------------------------------------------------


def upload_to_pypi() -> None:
    """Upload build artifacts to PyPI using twine.

    Raises:
        SystemExit: If twine is not installed or the upload fails.
    """
    result = run([sys.executable, "-m", "twine", "--version"], capture=True, check=False)
    if result.returncode != 0:
        die(
            "twine is not installed. Install it with:\n"
            "  pip install twine\n"
            "Then re-run this script."
        )

    run([sys.executable, "-m", "twine", "upload", str(DIST_DIR / "*")])
    print("  Uploaded to PyPI")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the release script."""
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    new_version = sys.argv[1].lstrip("v")  # Accept both "0.2.0" and "v0.2.0"

    print("\nHomeHost Release Script")
    print("=" * 60)

    # --- Pre-flight checks ---
    section("Step 1/11 — Validating version")
    validate_version(new_version)
    current_version = get_current_version()
    print(f"  Current version: {current_version}")
    print(f"  New version:     {new_version}")

    section("Step 2/11 — Checking git state")
    check_git_clean()
    check_on_main_branch()
    check_tag_does_not_exist(new_version)
    print("  Working tree clean, on main branch, tag does not exist")

    # --- Confirm ---
    print(f"\n  Ready to release HomeHost v{new_version}.")
    print("  This will:")
    print(f"    • Bump version to {new_version} in __init__.py and pyproject.toml")
    print("    • Update CHANGELOG.md")
    print(f"    • Commit and tag v{new_version}")
    print("    • Push to origin")
    print("    • Build and upload to PyPI")
    print()
    if not confirm("  Proceed?"):
        print("  Aborted.")
        sys.exit(0)

    # --- Make changes ---
    section("Step 3/11 — Updating homehost/__init__.py")
    update_init_version(new_version)

    section("Step 4/11 — Updating pyproject.toml")
    update_pyproject_version(new_version)

    section("Step 5/11 — Updating CHANGELOG.md")
    update_changelog(new_version)

    section("Step 6/11 — Creating git commit")
    git_commit(new_version)

    section("Step 7/11 — Creating git tag")
    git_tag(new_version)

    section("Step 8/11 — Pushing to origin")
    git_push(new_version)

    section("Step 9/11 — Building package")
    build_package()

    section("Step 10/11 — Uploading to PyPI")
    upload_to_pypi()

    section("Step 11/11 — Done")
    print(f"  HomeHost v{new_version} released successfully!")
    print(f"  PyPI: https://pypi.org/project/homehost/{new_version}/")
    print(f"  GitHub: https://github.com/homehost-dev/homehost/releases/tag/v{new_version}")
    print()


if __name__ == "__main__":
    main()
