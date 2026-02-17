# Superwhisper Archiver Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Archive superwhisper Meeting-mode recordings as markdown files in a git-backed repository, mirroring granola-archiver's modular architecture.

**Architecture:** Five Python modules — scanner (reads local recording dirs), markdown_formatter (meta.json → markdown), git_manager (write/commit/push), state_tracker (SQLite dedup), main (CLI orchestration). Config via YAML, state via SQLite, output as markdown with YAML frontmatter.

**Tech Stack:** Python 3.13+, uv, pydantic, pyyaml, gitpython, rich, pytest

**Design doc:** `docs/plans/2026-02-16-superwhisper-archiver-design.md`

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `archiver/__init__.py`
- Create: `config.yaml`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "superwhisper-archiver"
version = "0.1.0"
description = "Archive superwhisper recordings as markdown to a git repository"
authors = [
    { name = "Anjor Kanekar" },
]
readme = "README.md"
requires-python = ">=3.13"
license = { text = "MIT" }
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "gitpython>=3.1",
    "rich>=13.0",
]

[project.scripts]
archiver = "archiver.main:main"

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "ruff>=0.1.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["archiver"]

[tool.ruff]
line-length = 100
target-version = "py313"
```

**Step 2: Create archiver/__init__.py**

Empty file.

**Step 3: Create config.yaml**

```yaml
# Superwhisper Archiver Configuration
superwhisper:
  recordings_path: /Users/anjor/Documents/superwhisper/recordings

archive:
  repo_path: /path/to/archive-repo  # UPDATE THIS
  remote_name: origin
  default_branch: main

filters:
  modes: ["meeting"]
  min_duration_ms: 0

logging:
  level: INFO
  file: /tmp/superwhisper-archiver.log
```

**Step 4: Initialize uv project and install deps**

Run: `uv sync`
Expected: Dependencies installed successfully

**Step 5: Commit**

```bash
git add pyproject.toml archiver/__init__.py config.yaml
git commit -m "feat: scaffold superwhisper-archiver project"
```

---

### Task 2: Pydantic models

**Files:**
- Create: `archiver/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
from archiver.models import ArchiverConfig, Recording, ArchiveResult, ArchiveSummary


def test_archiver_config_from_dict():
    config_dict = {
        "superwhisper": {"recordings_path": "/tmp/recordings"},
        "archive": {"repo_path": "/tmp/repo"},
        "filters": {"modes": ["meeting"], "min_duration_ms": 0},
        "logging": {"level": "INFO", "file": "/tmp/test.log"},
    }
    config = ArchiverConfig(**config_dict)
    assert config.superwhisper.recordings_path == "/tmp/recordings"
    assert config.archive.repo_path == "/tmp/repo"
    assert config.filters.modes == ["meeting"]


def test_recording_from_meta_json():
    meta = {
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello world",
        "rawResult": " Hello world",
        "duration": 13647,
        "segments": [{"text": "Hello world", "start": 1.696, "end": 12.864}],
        "modeName": "Meeting",
        "modelName": "Ultra (Cloud)",
        "languageModelName": "GPT-5 mini",
        "languageSelected": "en",
        "systemAudioEnabled": True,
        "appVersion": "2.9.0",
    }
    recording = Recording(source_dir="1770978710", **meta)
    assert recording.source_dir == "1770978710"
    assert recording.modeName == "Meeting"
    assert recording.duration == 13647
    assert len(recording.segments) == 1


def test_recording_with_llm_result():
    meta = {
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello",
        "rawResult": " Hello",
        "duration": 5000,
        "segments": [],
        "modeName": "Meeting",
        "modelName": "Ultra (Cloud)",
        "languageSelected": "en",
        "systemAudioEnabled": True,
        "appVersion": "2.9.0",
        "llmResult": "Summary: greeting exchanged",
    }
    recording = Recording(source_dir="123", **meta)
    assert recording.llmResult == "Summary: greeting exchanged"


def test_recording_without_optional_fields():
    meta = {
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello",
        "rawResult": " Hello",
        "duration": 5000,
        "segments": [],
        "modeName": "Default",
        "modelName": "Ultra (Cloud)",
        "languageSelected": "en",
        "systemAudioEnabled": False,
        "appVersion": "2.9.0",
    }
    recording = Recording(source_dir="123", **meta)
    assert recording.llmResult is None
    assert recording.languageModelName is None


def test_archive_result():
    result = ArchiveResult(
        success=True,
        source_dir="1770978710",
        file_path="2026/02/2026-02-13-10-31-50.md",
        commit_sha="abc123",
    )
    assert result.success
    assert result.error is None


def test_archive_summary():
    summary = ArchiveSummary(
        total_recordings=5,
        archived_count=3,
        failed_count=1,
        skipped_count=1,
        results=[],
    )
    assert summary.total_recordings == 5
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# archiver/models.py
"""Pydantic models for the superwhisper archiver."""

from typing import Optional, List
from pydantic import BaseModel, Field


class Segment(BaseModel):
    text: str
    start: float
    end: float


class Recording(BaseModel):
    """A parsed superwhisper recording from meta.json."""

    source_dir: str
    datetime: str
    result: str
    rawResult: str
    duration: int  # milliseconds
    segments: List[Segment]
    modeName: str
    modelName: str
    languageSelected: str
    systemAudioEnabled: bool
    appVersion: str
    languageModelName: Optional[str] = None
    llmResult: Optional[str] = None

    class Config:
        extra = "ignore"


class ArchiverConfig(BaseModel):
    """Configuration for the archiver."""

    class SuperwhisperConfig(BaseModel):
        recordings_path: str

    class ArchiveConfig(BaseModel):
        repo_path: str
        remote_name: str = "origin"
        default_branch: str = "main"

    class FiltersConfig(BaseModel):
        modes: List[str] = Field(default_factory=lambda: ["meeting"])
        min_duration_ms: int = 0

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        file: str = "/tmp/superwhisper-archiver.log"

    superwhisper: SuperwhisperConfig
    archive: ArchiveConfig
    filters: FiltersConfig
    logging: LoggingConfig


class ArchiveResult(BaseModel):
    """Result of archiving a single recording."""

    success: bool
    source_dir: str
    error: Optional[str] = None
    file_path: Optional[str] = None
    commit_sha: Optional[str] = None


class ArchiveSummary(BaseModel):
    """Summary of an archive run."""

    total_recordings: int
    archived_count: int
    failed_count: int
    skipped_count: int
    results: List[ArchiveResult]
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add archiver/models.py tests/test_models.py
git commit -m "feat: add pydantic models for recordings, config, and results"
```

---

### Task 3: Scanner module

**Files:**
- Create: `archiver/scanner.py`
- Create: `tests/test_scanner.py`

**Step 1: Write the failing test**

```python
# tests/test_scanner.py
import json
from pathlib import Path

from archiver.scanner import Scanner
from archiver.models import Recording


def _create_recording(tmp_path: Path, dir_name: str, meta: dict):
    """Helper to create a fake recording directory."""
    rec_dir = tmp_path / dir_name
    rec_dir.mkdir()
    (rec_dir / "meta.json").write_text(json.dumps(meta))


MEETING_META = {
    "datetime": "2026-02-13T10:31:50",
    "result": "Hello world",
    "rawResult": " Hello world",
    "duration": 13647,
    "segments": [{"text": "Hello world", "start": 1.0, "end": 12.0}],
    "modeName": "Meeting",
    "modelName": "Ultra (Cloud)",
    "languageSelected": "en",
    "systemAudioEnabled": True,
    "appVersion": "2.9.0",
}

DEFAULT_META = {
    **MEETING_META,
    "modeName": "Default",
    "datetime": "2026-02-14T09:00:00",
}


def test_scan_finds_recordings(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", DEFAULT_META)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan()
    assert len(recordings) == 2


def test_scan_filters_by_mode(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", DEFAULT_META)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan(modes=["meeting"])
    assert len(recordings) == 1
    assert recordings[0].modeName == "Meeting"


def test_scan_filters_by_min_duration(tmp_path):
    short_meta = {**MEETING_META, "duration": 100}
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", short_meta)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan(min_duration_ms=1000)
    assert len(recordings) == 1


def test_scan_filters_by_since_date(tmp_path):
    old_meta = {**MEETING_META, "datetime": "2026-02-01T10:00:00"}
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", old_meta)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan(since="2026-02-10")
    assert len(recordings) == 1


def test_scan_skips_invalid_directories(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    # Create a directory without meta.json
    (tmp_path / "invalid_dir").mkdir()
    # Create a non-directory file
    (tmp_path / "random_file.txt").write_text("hello")
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan()
    assert len(recordings) == 1


def test_scan_returns_sorted_by_datetime(tmp_path):
    early = {**MEETING_META, "datetime": "2026-02-10T08:00:00"}
    late = {**MEETING_META, "datetime": "2026-02-15T18:00:00"}
    _create_recording(tmp_path, "1770978720", late)
    _create_recording(tmp_path, "1770978710", early)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan()
    assert recordings[0].datetime == "2026-02-10T08:00:00"
    assert recordings[1].datetime == "2026-02-15T18:00:00"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scanner.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# archiver/scanner.py
"""Scans the local superwhisper recordings directory."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .models import Recording

logger = logging.getLogger(__name__)


class Scanner:
    """Scans superwhisper recordings directory and parses meta.json files."""

    def __init__(self, recordings_path: str):
        self.recordings_path = Path(recordings_path)

    def scan(
        self,
        modes: Optional[List[str]] = None,
        min_duration_ms: int = 0,
        since: Optional[str] = None,
    ) -> List[Recording]:
        """Scan for recordings, applying optional filters.

        Args:
            modes: Filter to these mode names (case-insensitive). None = all modes.
            min_duration_ms: Skip recordings shorter than this (milliseconds).
            since: Only include recordings with datetime >= this ISO date string.

        Returns:
            List of Recording objects, sorted by datetime ascending.
        """
        recordings = []

        if not self.recordings_path.exists():
            logger.warning(f"Recordings path does not exist: {self.recordings_path}")
            return recordings

        for entry in self.recordings_path.iterdir():
            if not entry.is_dir():
                continue

            meta_path = entry / "meta.json"
            if not meta_path.exists():
                logger.debug(f"Skipping {entry.name}: no meta.json")
                continue

            try:
                meta = json.loads(meta_path.read_text())
                recording = Recording(source_dir=entry.name, **meta)
                recordings.append(recording)
            except Exception as e:
                logger.warning(f"Failed to parse {meta_path}: {e}")
                continue

        # Apply filters
        if modes:
            modes_lower = [m.lower() for m in modes]
            recordings = [r for r in recordings if r.modeName.lower() in modes_lower]

        if min_duration_ms > 0:
            recordings = [r for r in recordings if r.duration >= min_duration_ms]

        if since:
            since_dt = datetime.fromisoformat(since)
            recordings = [
                r for r in recordings if datetime.fromisoformat(r.datetime) >= since_dt
            ]

        # Sort by datetime ascending
        recordings.sort(key=lambda r: r.datetime)

        return recordings
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_scanner.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add archiver/scanner.py tests/test_scanner.py
git commit -m "feat: add scanner module to read local superwhisper recordings"
```

---

### Task 4: Markdown formatter

**Files:**
- Create: `archiver/markdown_formatter.py`
- Create: `tests/test_markdown_formatter.py`

**Step 1: Write the failing test**

```python
# tests/test_markdown_formatter.py
from archiver.markdown_formatter import MarkdownFormatter
from archiver.models import Recording


def _make_recording(**overrides) -> Recording:
    defaults = {
        "source_dir": "1770978710",
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello world. How are you?",
        "rawResult": " Hello world. How are you?",
        "duration": 13647,
        "segments": [
            {"text": "Hello world.", "start": 1.696, "end": 5.0},
            {"text": "How are you?", "start": 5.5, "end": 12.864},
        ],
        "modeName": "Meeting",
        "modelName": "Ultra (Cloud)",
        "languageModelName": "GPT-5 mini",
        "languageSelected": "en",
        "systemAudioEnabled": True,
        "appVersion": "2.9.0",
    }
    defaults.update(overrides)
    return Recording(**defaults)


def test_format_contains_frontmatter():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert md.startswith("---\n")
    assert "datetime: " in md
    assert "mode: meeting" in md.lower() or "mode: Meeting" in md
    assert "source_dir: " in md


def test_format_contains_transcription():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Transcription" in md
    assert "Hello world. How are you?" in md


def test_format_contains_segments():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Segments" in md
    assert "Hello world." in md
    assert "How are you?" in md


def test_format_contains_duration():
    rec = _make_recording(duration=90000)  # 90 seconds
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "1m 30s" in md


def test_format_with_llm_result():
    rec = _make_recording(llmResult="Summary: a greeting was exchanged.")
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Summary" in md
    assert "a greeting was exchanged" in md


def test_format_without_llm_result():
    rec = _make_recording()
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "## Summary" not in md


def test_compute_file_path():
    rec = _make_recording(datetime="2026-02-13T10:31:50")
    fmt = MarkdownFormatter()
    path = fmt.compute_file_path(rec)
    assert path == "2026/02/2026-02-13-10-31-50.md"


def test_compute_file_path_different_date():
    rec = _make_recording(datetime="2026-01-05T23:59:01")
    fmt = MarkdownFormatter()
    path = fmt.compute_file_path(rec)
    assert path == "2026/01/2026-01-05-23-59-01.md"


def test_format_duration_hours():
    rec = _make_recording(duration=3723000)  # 1h 2m 3s
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    assert "1h 2m 3s" in md


def test_format_segments_timestamps():
    rec = _make_recording(
        segments=[{"text": "Hello", "start": 65.5, "end": 70.2}]
    )
    fmt = MarkdownFormatter()
    md = fmt.format_recording(rec)
    # Should format as MM:SS.s
    assert "01:05.5" in md
    assert "01:10.2" in md
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_markdown_formatter.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# archiver/markdown_formatter.py
"""Formats superwhisper recordings as Markdown."""

from datetime import datetime
import logging

from .models import Recording

logger = logging.getLogger(__name__)


class MarkdownFormatter:
    """Formats superwhisper recordings as Markdown with YAML frontmatter."""

    def format_recording(self, recording: Recording) -> str:
        """Format a recording as Markdown.

        Args:
            recording: The Recording to format.

        Returns:
            Formatted Markdown string.
        """
        frontmatter = self._build_frontmatter(recording)
        body = self._build_body(recording)
        return frontmatter + body

    def _build_frontmatter(self, rec: Recording) -> str:
        parts = [
            "---",
            f'datetime: "{rec.datetime}"',
            f"mode: {rec.modeName}",
            f"duration_ms: {rec.duration}",
            f'model: "{rec.modelName}"',
        ]
        if rec.languageModelName:
            parts.append(f'language_model: "{rec.languageModelName}"')
        parts.extend([
            f"language: {rec.languageSelected}",
            f"system_audio: {str(rec.systemAudioEnabled).lower()}",
            f'app_version: "{rec.appVersion}"',
            f'source_dir: "{rec.source_dir}"',
            f'archived_at: "{datetime.now().isoformat()}"',
            "---",
        ])
        return "\n".join(parts) + "\n"

    def _build_body(self, rec: Recording) -> str:
        dt = datetime.fromisoformat(rec.datetime)
        duration_str = self._format_duration(rec.duration)

        parts = [
            f"\n# Recording — {dt.strftime('%Y-%m-%d %H:%M')}\n",
            f"**Mode**: {rec.modeName} | **Duration**: {duration_str}\n",
        ]

        # Transcription
        transcription = rec.result.strip() if rec.result else rec.rawResult.strip()
        if transcription:
            parts.append(f"## Transcription\n\n{transcription}\n")

        # LLM Summary (if present)
        if rec.llmResult:
            parts.append(f"## Summary\n\n{rec.llmResult}\n")

        # Segments
        if rec.segments:
            lines = []
            for seg in rec.segments:
                start = self._format_timestamp(seg.start)
                end = self._format_timestamp(seg.end)
                lines.append(f"- [{start} → {end}] {seg.text}")
            parts.append("## Segments\n\n" + "\n".join(lines) + "\n")

        # Footer
        parts.append(f"\n---\n*Archived: {datetime.now().strftime('%Y-%m-%d')}*\n")

        return "\n".join(parts)

    def compute_file_path(self, recording: Recording) -> str:
        """Compute the archive file path for a recording.

        Returns:
            Relative path like YYYY/MM/YYYY-MM-DD-HH-MM-SS.md
        """
        dt = datetime.fromisoformat(recording.datetime)
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        filename = dt.strftime("%Y-%m-%d-%H-%M-%S") + ".md"
        return f"{year}/{month}/{filename}"

    @staticmethod
    def _format_duration(duration_ms: int) -> str:
        total_seconds = duration_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as MM:SS.s"""
        mins = int(seconds) // 60
        secs = seconds - (mins * 60)
        return f"{mins:02d}:{secs:04.1f}"
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_markdown_formatter.py -v`
Expected: All 10 tests PASS

**Step 5: Commit**

```bash
git add archiver/markdown_formatter.py tests/test_markdown_formatter.py
git commit -m "feat: add markdown formatter for superwhisper recordings"
```

---

### Task 5: State tracker

**Files:**
- Create: `archiver/state_tracker.py`
- Create: `tests/test_state_tracker.py`

**Step 1: Write the failing test**

```python
# tests/test_state_tracker.py
from archiver.state_tracker import StateTracker


def test_is_archived_returns_false_for_unknown(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.is_archived("unknown_dir") is False


def test_mark_and_check_archived(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.mark_archived(
        source_dir="1770978710",
        recording_datetime="2026-02-13T10:31:50",
        mode="Meeting",
        duration_ms=13647,
        file_path="2026/02/2026-02-13-10-31-50.md",
        commit_sha="abc123",
    )
    assert tracker.is_archived("1770978710") is True


def test_get_archived_count(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_archived_count() == 0
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha1")
    tracker.mark_archived("dir2", "2026-02-13T11:00:00", "Meeting", 6000, "b.md", "sha2")
    assert tracker.get_archived_count() == 2


def test_update_and_get_last_run(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    assert tracker.get_last_run_timestamp() is None
    tracker.update_last_run(
        recordings_processed=5,
        recordings_archived=3,
        recordings_failed=1,
    )
    ts = tracker.get_last_run_timestamp()
    assert ts is not None


def test_mark_archived_is_idempotent(tmp_path):
    tracker = StateTracker(str(tmp_path / "test.db"))
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha1")
    tracker.mark_archived("dir1", "2026-02-13T10:00:00", "Meeting", 5000, "a.md", "sha2")
    assert tracker.get_archived_count() == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_state_tracker.py -v`
Expected: FAIL with ImportError

**Step 3: Write minimal implementation**

```python
# archiver/state_tracker.py
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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_state_tracker.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add archiver/state_tracker.py tests/test_state_tracker.py
git commit -m "feat: add SQLite state tracker for deduplication"
```

---

### Task 6: Git manager

**Files:**
- Create: `archiver/git_manager.py`

This module is a direct adaptation from granola-archiver's `git_manager.py`. It wraps GitPython for write/commit/push operations. Since it requires a real git repo to test meaningfully and the logic is straightforward, we'll test it through integration in the main module.

**Step 1: Write implementation**

```python
# archiver/git_manager.py
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
```

**Step 2: Commit**

```bash
git add archiver/git_manager.py
git commit -m "feat: add git manager for write/commit/push operations"
```

---

### Task 7: Main orchestrator + CLI

**Files:**
- Create: `archiver/main.py`

**Step 1: Write implementation**

```python
# archiver/main.py
"""Main orchestrator for the superwhisper archiver."""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .models import ArchiverConfig, ArchiveResult, ArchiveSummary
from .scanner import Scanner
from .markdown_formatter import MarkdownFormatter
from .git_manager import GitManager
from .state_tracker import StateTracker

console = Console()


def setup_logging(config: ArchiverConfig):
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    log_file = Path(config.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            logging.FileHandler(config.logging.file),
        ],
    )


def load_config(config_path: Optional[str] = None) -> ArchiverConfig:
    if config_path:
        path = Path(config_path)
    else:
        path = Path("config.yaml")

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    console.print(f"[dim]Using config: {path}[/dim]")
    with open(path, "r") as f:
        config_dict = yaml.safe_load(f)
    return ArchiverConfig(**config_dict)


def archive_recording(
    recording,
    formatter: MarkdownFormatter,
    git_manager: GitManager,
    state_tracker: StateTracker,
    dry_run: bool = False,
) -> ArchiveResult:
    logger = logging.getLogger(__name__)

    try:
        markdown = formatter.format_recording(recording)
        file_path = formatter.compute_file_path(recording)

        if dry_run:
            console.print(f"[yellow]DRY RUN: Would archive {recording.source_dir} to {file_path}[/yellow]")
            return ArchiveResult(success=True, source_dir=recording.source_dir, file_path=file_path)

        dt = datetime.fromisoformat(recording.datetime)
        commit_message = (
            f"Archive: {recording.modeName} recording {dt.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Source: {recording.source_dir}\n"
            f"Duration: {recording.duration}ms\n"
        )
        commit_sha = git_manager.write_and_commit(file_path, markdown, commit_message)

        if not commit_sha:
            raise Exception("Failed to commit recording")

        state_tracker.mark_archived(
            source_dir=recording.source_dir,
            recording_datetime=recording.datetime,
            mode=recording.modeName,
            duration_ms=recording.duration,
            file_path=file_path,
            commit_sha=commit_sha,
        )

        logger.info(f"Archived {recording.source_dir} to {file_path}")
        return ArchiveResult(
            success=True,
            source_dir=recording.source_dir,
            file_path=file_path,
            commit_sha=commit_sha,
        )

    except Exception as e:
        logger.error(f"Failed to archive {recording.source_dir}: {e}", exc_info=True)
        return ArchiveResult(success=False, source_dir=recording.source_dir, error=str(e))


def run_archiver(
    config: ArchiverConfig,
    dry_run: bool = False,
    backfill: bool = False,
    since_date: Optional[str] = None,
    modes_override: Optional[str] = None,
) -> ArchiveSummary:
    logger = logging.getLogger(__name__)
    logger.info("Starting archiver run")

    scanner = Scanner(config.superwhisper.recordings_path)
    state_tracker = StateTracker("state/archive_state.db")
    git_manager = GitManager(
        config.archive.repo_path,
        config.archive.remote_name,
        config.archive.default_branch,
    )
    formatter = MarkdownFormatter()

    if not dry_run:
        git_manager.ensure_up_to_date()

    # Determine mode filter
    modes = modes_override.split(",") if modes_override else config.filters.modes

    # Determine since filter
    since = None
    if not backfill:
        if since_date:
            since = since_date
        else:
            last_run = state_tracker.get_last_run_timestamp()
            if last_run:
                since = last_run.isoformat()

    # Scan recordings
    recordings = scanner.scan(
        modes=modes if modes else None,
        min_duration_ms=config.filters.min_duration_ms,
        since=since,
    )

    # Filter already-archived
    results = []
    skipped_count = 0

    for rec in recordings:
        if state_tracker.is_archived(rec.source_dir):
            logger.info(f"Skipping {rec.source_dir} — already archived")
            skipped_count += 1
            continue

        result = archive_recording(rec, formatter, git_manager, state_tracker, dry_run)
        results.append(result)

    # Push
    if not dry_run and any(r.success for r in results):
        git_manager.push_to_remote()

    # Update run stats
    if not dry_run:
        archived_count = sum(1 for r in results if r.success)
        failed_count = sum(1 for r in results if not r.success)
        state_tracker.update_last_run(
            recordings_processed=len(recordings),
            recordings_archived=archived_count,
            recordings_failed=failed_count,
        )

    summary = ArchiveSummary(
        total_recordings=len(recordings),
        archived_count=sum(1 for r in results if r.success),
        failed_count=sum(1 for r in results if not r.success),
        skipped_count=skipped_count,
        results=results,
    )

    logger.info(
        f"Run complete: {summary.archived_count} archived, "
        f"{summary.failed_count} failed, {summary.skipped_count} skipped"
    )
    return summary


def print_summary(summary: ArchiveSummary):
    table = Table(title="Archive Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")

    table.add_row("Total Recordings", str(summary.total_recordings))
    table.add_row("Archived", str(summary.archived_count))
    table.add_row("Failed", str(summary.failed_count))
    table.add_row("Skipped", str(summary.skipped_count))

    console.print(table)

    if summary.failed_count > 0:
        console.print("\n[red]Failed:[/red]")
        for result in summary.results:
            if not result.success:
                console.print(f"  - {result.source_dir}: {result.error}")


def main():
    parser = argparse.ArgumentParser(description="Archive superwhisper recordings to a git repository")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be archived")
    parser.add_argument("--backfill", action="store_true", help="Archive ALL matching recordings")
    parser.add_argument("--since", type=str, help="Archive recordings since this date (ISO format)")
    parser.add_argument("--modes", type=str, help="Override mode filter (comma-separated, e.g. meeting,super)")

    args = parser.parse_args()

    try:
        config = load_config(args.config)
        setup_logging(config)
        summary = run_archiver(
            config,
            dry_run=args.dry_run,
            backfill=args.backfill,
            since_date=args.since,
            modes_override=args.modes,
        )
        print_summary(summary)
        sys.exit(0 if summary.failed_count == 0 else 1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        logging.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add archiver/main.py
git commit -m "feat: add main orchestrator with CLI interface"
```

---

### Task 8: Add .gitignore and finalize

**Files:**
- Create: `.gitignore`

**Step 1: Create .gitignore**

```
state/
__pycache__/
*.pyc
.ruff_cache/
*.egg-info/
dist/
logs/
```

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore"
```

---

### Task 9: End-to-end dry-run test

**Step 1: Update config.yaml with a real archive repo path (or a temp path)**

The config needs `archive.repo_path` pointing to a real git repo. For testing, we can create a temporary one.

**Step 2: Run dry-run against real superwhisper data**

Run: `uv run python -m archiver --dry-run --backfill`
Expected: Output showing the 5 Meeting-mode recordings that would be archived, with their computed file paths. No git operations performed.

**Step 3: Verify output makes sense**

Check that:
- Only Meeting-mode recordings appear
- File paths follow `YYYY/MM/YYYY-MM-DD-HH-MM-SS.md` format
- Summary table shows correct counts

**Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix: adjustments from dry-run testing"
```

---

### Task 10: Live test with real archive repo

**Step 1: Create or configure the archive git repo**

Either create a new GitHub repo for the archive, or use an existing one. Update `config.yaml` with the correct `repo_path`.

**Step 2: Run archiver for real**

Run: `uv run python -m archiver --backfill`
Expected: 5 Meeting recordings archived, committed, and pushed. Summary table shows 5 archived, 0 failed, 0 skipped.

**Step 3: Verify the archive repo**

Check the archive repo for:
- Correct directory structure (`2026/02/`)
- Markdown files with proper frontmatter and content
- Git history with descriptive commit messages

**Step 4: Run again to verify idempotency**

Run: `uv run python -m archiver --backfill`
Expected: 0 archived, 5 skipped (all already archived).
