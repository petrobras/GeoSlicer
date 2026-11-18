import git
import logging
from pathlib import Path
from typing import Set


class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


def get_repo_root() -> Path:
    """Finds the git repository root based on the current execution context."""
    try:
        # Search upward from the Current Working Directory for the .git folder
        repo = git.Repo(Path.cwd(), search_parent_directories=True)
        return Path(repo.working_tree_dir).resolve()
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        # Fallback to CWD if running outside of a git repo context
        return Path.cwd().resolve()


def find_submodules_setup_directory(path: Path) -> Set[Path]:
    """Find directories containing setup.py or pyproject.toml in submodules."""
    setup_dir_list = []

    for filename in ["setup.py", "pyproject.toml"]:
        setup_base_dir = [
            file_path.parent for file_path in path.rglob(filename) if ".venv" not in file_path.relative_to(path).parts
        ]
        setup_dir_list.extend(setup_base_dir)

    return set(setup_dir_list)
