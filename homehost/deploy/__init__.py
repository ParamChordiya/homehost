"""HomeHost deployment modules."""

from homehost.deploy.git import (
    get_current_branch,
    get_latest_commit,
    has_uncommitted_changes,
    is_git_repo,
    pull_latest,
)
from homehost.deploy.scaffold import (
    TemplateType,
    get_template_dir,
    list_templates,
    scaffold_project,
)
from homehost.deploy.watcher import ChangeEvent, ProjectWatcher

__all__ = [
    # git
    "is_git_repo",
    "get_current_branch",
    "get_latest_commit",
    "pull_latest",
    "has_uncommitted_changes",
    # scaffold
    "TemplateType",
    "scaffold_project",
    "get_template_dir",
    "list_templates",
    # watcher
    "ProjectWatcher",
    "ChangeEvent",
]
