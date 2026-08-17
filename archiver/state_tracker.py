"""SQLite-based state tracker for archived recordings."""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StateTracker:
    """Tracks which recordings have been archived using SQLite."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archived_recordings (
                    source_dir TEXT PRIMARY KEY,
                    datetime TEXT,
                    mode TEXT,
                    duration_ms INTEGER,
                    file_path TEXT NOT NULL,
                    commit_sha TEXT,
                    archived_at TEXT NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS archive_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at TEXT NOT NULL,
                    recordings_processed INTEGER DEFAULT 0,
                    recordings_archived INTEGER DEFAULT 0,
                    recordings_failed INTEGER DEFAULT 0
                )
            """)
            # Failures retry automatically — an unarchived recording is simply
            # rescanned on the next run. This table exists only to count how
            # long something has been failing, so it can be alerted on.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS failed_recordings (
                    source_dir TEXT PRIMARY KEY,
                    first_failed_at TEXT NOT NULL,
                    last_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 1
                )
            """)
            conn.commit()

    def is_archived(self, source_dir: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM archived_recordings WHERE source_dir = ?",
                (source_dir,),
            )
            return cursor.fetchone() is not None

    def get_archived_source_dirs(self) -> set:
        """Every source_dir already archived, for cheap scan-time deduplication."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT source_dir FROM archived_recordings")
            return {row[0] for row in cursor.fetchall()}

    def mark_archived(
        self,
        source_dir: str,
        recording_datetime: str,
        mode: str,
        duration_ms: int,
        file_path: str,
        commit_sha: Optional[str] = None,
    ):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO archived_recordings
                (source_dir, datetime, mode, duration_ms, file_path, commit_sha, archived_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_dir,
                    recording_datetime,
                    mode,
                    duration_ms,
                    file_path,
                    commit_sha,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            logger.info(f"Marked {source_dir} as archived at {file_path}")

    def get_last_run_timestamp(self) -> Optional[datetime]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT run_at FROM archive_runs ORDER BY run_at DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return datetime.fromisoformat(row[0])
            return None

    def update_last_run(
        self,
        recordings_processed: int = 0,
        recordings_archived: int = 0,
        recordings_failed: int = 0,
    ):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO archive_runs
                (run_at, recordings_processed, recordings_archived, recordings_failed)
                VALUES (?, ?, ?, ?)
                """,
                (
                    datetime.now().isoformat(),
                    recordings_processed,
                    recordings_archived,
                    recordings_failed,
                ),
            )
            conn.commit()

    def record_failure(self, source_dir: str, error: Optional[str] = None):
        """Note that a recording failed to archive, incrementing its attempt count."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO failed_recordings
                    (source_dir, first_failed_at, last_error, attempts)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(source_dir) DO UPDATE SET
                    last_error = excluded.last_error,
                    attempts = failed_recordings.attempts + 1
                """,
                (source_dir, datetime.now().isoformat(), error),
            )
            conn.commit()

    def clear_failure(self, source_dir: str):
        """Forget a recording's failure history, after it archives successfully."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM failed_recordings WHERE source_dir = ?",
                (source_dir,),
            )
            conn.commit()

    def get_failures(self) -> list:
        """Recordings currently failing to archive, oldest failure first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT source_dir, first_failed_at, last_error, attempts
                FROM failed_recordings
                ORDER BY first_failed_at ASC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_archived_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM archived_recordings")
            return cursor.fetchone()[0]
