"""Git operations for archiving recordings."""

import logging
from pathlib import Path
from typing import Optional

try:
    from git import Repo, GitCommandError
except ImportError:
    raise ImportError("GitPython not installed. Install with: pip install gitpython")

logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git operations for the archive repository."""

    def __init__(self, repo_path: str, remote_name: str = "origin", default_branch: str = "main"):
        self.repo_path = Path(repo_path)
        self.remote_name = remote_name
        self.default_branch = default_branch

        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")

        try:
            self.repo = Repo(self.repo_path)
        except Exception as e:
            raise ValueError(f"Invalid git repository at {repo_path}: {e}")

    def ensure_up_to_date(self):
        try:
            if self.repo.active_branch.name != self.default_branch:
                self.repo.git.checkout(self.default_branch)
            origin = self.repo.remote(name=self.remote_name)
            origin.pull(self.default_branch)
        except GitCommandError as e:
            logger.warning(f"Failed to update repository: {e}")

    def write_and_commit(self, file_path: str, content: str, commit_message: str) -> Optional[str]:
        try:
            full_path = self.repo_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            self.repo.index.add([file_path])
            commit = self.repo.index.commit(commit_message)
            commit_sha = commit.hexsha
            logger.info(f"Committed {file_path} with SHA {commit_sha[:8]}")
            return commit_sha
        except Exception as e:
            logger.error(f"Failed to write and commit {file_path}: {e}")
            return None

    def push_to_remote(self) -> bool:
        try:
            origin = self.repo.remote(name=self.remote_name)
            origin.push(self.default_branch)
            logger.info("Push successful")
            return True
        except GitCommandError as e:
            logger.error(f"Failed to push to remote: {e}")
            return False
