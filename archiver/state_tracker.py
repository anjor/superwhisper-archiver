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
            conn.commit()

    def is_archived(self, source_dir: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM archived_recordings WHERE source_dir = ?",
                (source_dir,),
            )
            return cursor.fetchone() is not None

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

    def get_archived_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM archived_recordings")
            return cursor.fetchone()[0]
