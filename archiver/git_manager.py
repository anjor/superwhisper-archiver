"""Git operations for archiving recordings."""

import logging
import time
from pathlib import Path
from typing import Optional

try:
    from git import Repo, GitCommandError
except ImportError:
    raise ImportError("GitPython not installed. Install with: pip install gitpython")

logger = logging.getLogger(__name__)

# A git index.lock older than this is treated as stale (left by an interrupted
# process) and safe to remove. The archiver runs briefly on a schedule, so any
# lock surviving this long is not from a live run. Kept conservative to avoid
# racing a legitimate concurrent git operation.
STALE_LOCK_SECONDS = 300


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
            logger.info(f"Wrote file: {file_path}")

            # Write succeeded; staging + committing may hit a stale lock.
            return self._stage_and_commit(file_path, commit_message)
        except Exception as e:
            logger.error(f"Failed to write and commit {file_path}: {e}")
            return None

    def _stage_and_commit(self, file_path: str, commit_message: str) -> Optional[str]:
        """Stage and commit a written file, recovering from a stale index.lock.

        If the commit fails and a *stale* lock is present, the lock is removed
        and the commit is retried once. A fresh lock is left untouched, since it
        may belong to a live git process.
        """
        try:
            self.repo.index.add([file_path])
            commit = self.repo.index.commit(commit_message)
            logger.info(f"Committed {file_path} with SHA {commit.hexsha[:8]}")
            return commit.hexsha
        except Exception as e:
            if not self._clear_stale_lock():
                raise
            logger.warning(f"Cleared stale git lock; retrying commit of {file_path} (was: {e})")
            self.repo.index.add([file_path])
            commit = self.repo.index.commit(commit_message)
            logger.info(f"Committed {file_path} with SHA {commit.hexsha[:8]}")
            return commit.hexsha

    def _clear_stale_lock(self) -> bool:
        """Remove the repo's index.lock if it is stale.

        Returns:
            True if a stale lock was found and removed, False otherwise.
        """
        lock_path = Path(self.repo.git_dir) / "index.lock"
        if not lock_path.exists():
            return False

        age = time.time() - lock_path.stat().st_mtime
        if age < STALE_LOCK_SECONDS:
            logger.warning(
                f"index.lock present but only {age:.0f}s old; leaving it "
                "(may be a live git process)"
            )
            return False

        try:
            lock_path.unlink()
            logger.warning(f"Removed stale index.lock ({age:.0f}s old) at {lock_path}")
            return True
        except OSError as e:
            logger.error(f"Could not remove stale index.lock: {e}")
            return False

    def push_to_remote(self) -> bool:
        try:
            origin = self.repo.remote(name=self.remote_name)
            origin.push(self.default_branch)
            logger.info("Push successful")
            return True
        except GitCommandError as e:
            logger.error(f"Failed to push to remote: {e}")
            return False
