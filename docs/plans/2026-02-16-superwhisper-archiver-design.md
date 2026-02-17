# Superwhisper Archiver — Design Document

**Date**: 2026-02-16
**Status**: Approved

## Goal

Archive superwhisper Meeting-mode recordings as markdown files in a git-backed repository, mirroring the architecture of granola-archiver. One-shot CLI command, markdown-only output (no audio files).

## Architecture

Modular Python project with 5 core modules:

```
superwhisper-archiver/
├── archiver/
│   ├── __init__.py
│   ├── main.py              # CLI entry point + orchestration
│   ├── scanner.py            # Scan local recordings directory
│   ├── markdown_formatter.py # meta.json → markdown
│   ├── git_manager.py        # Write, commit, push
│   ├── state_tracker.py      # SQLite dedup + run stats
│   └── models.py             # Pydantic data models
├── config.yaml
├── pyproject.toml
└── tests/
```

## Data Flow

1. **Scan** `/Users/anjor/Documents/superwhisper/recordings/` — list recording directories (Unix timestamp names), parse each `meta.json` into a Recording model.
2. **Filter & deduplicate** — check SQLite for already-archived recordings; apply mode filter (default: Meeting only), min duration, `--since` date.
3. **Format** each recording as markdown — YAML frontmatter with metadata, body with transcription and timed segments.
4. **Write, commit, push** — write to `YYYY/MM/YYYY-MM-DD-HH-MM-SS.md`, one commit per recording, push batch at end.

## Data Source

Superwhisper stores recordings locally at `/Users/anjor/Documents/superwhisper/recordings/`. Each recording is a directory named by Unix timestamp containing:

- `meta.json` — transcription text, segments with timing, mode, duration, model info, context
- `output.wav` — audio file (not archived)

Key `meta.json` fields: `datetime`, `result` (transcription), `rawResult`, `duration` (ms), `segments` (text + start/end), `modeName`, `modelName`, `languageModelName`, `systemAudioEnabled`, `appVersion`, `promptContext`.

## Markdown Output Format

```markdown
---
datetime: "2026-02-16T13:21:40"
mode: meeting
duration_ms: 28400000
model: "Ultra (Cloud)"
language_model: "GPT-5 mini"
language: en
system_audio: true
app_version: "2.9.0"
source_dir: "1770391763"
archived_at: "2026-02-16T18:00:00"
---

# Recording — 2026-02-16 13:21

**Mode**: Meeting | **Duration**: 28m 24s

## Transcription

Thank you. Let me check the agenda for today...

## Segments

- [00:00.0 → 00:00.3] Thank you.
- [00:01.2 → 00:05.8] Let me check the agenda for today...
```

File path: `YYYY/MM/YYYY-MM-DD-HH-MM-SS.md` (e.g., `2026/02/2026-02-16-13-21-40.md`)

## CLI Interface

```
python -m archiver                           # Archive new recordings since last run
python -m archiver --dry-run                 # Show what would be archived
python -m archiver --backfill                # Archive ALL matching recordings
python -m archiver --since 2026-02-10        # Archive from specific date
python -m archiver --modes meeting,super     # Override mode filter
```

## State Tracking (SQLite)

**`archived_recordings` table:**

| Column | Type | Description |
|--------|------|-------------|
| source_dir | TEXT PK | Unix timestamp directory name |
| datetime | TEXT | Recording datetime |
| mode | TEXT | Recording mode |
| duration_ms | INTEGER | Recording duration in ms |
| file_path | TEXT | Output markdown path |
| commit_sha | TEXT | Git commit SHA |
| archived_at | TEXT | When archived |

**`archive_runs` table:**

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| run_at | TEXT | Run timestamp |
| recordings_processed | INTEGER | Total evaluated |
| recordings_archived | INTEGER | Successfully archived |
| recordings_failed | INTEGER | Failed count |

## Configuration (config.yaml)

```yaml
superwhisper:
  recordings_path: /Users/anjor/Documents/superwhisper/recordings

archive:
  repo_path: /path/to/archive-repo
  remote_name: origin
  default_branch: main

filters:
  modes: ["meeting"]     # default: only Meeting mode
  min_duration_ms: 0

logging:
  level: INFO
  file: logs/archiver.log
```

## Technology

- Python 3.13+, managed with `uv`
- Dependencies: pydantic, pyyaml, gitpython, rich
- No API calls needed — data is local filesystem
- Async not required (local I/O), but can use sync throughout

## Key Differences from Granola-Archiver

| Aspect | Granola-Archiver | Superwhisper-Archiver |
|--------|-----------------|----------------------|
| Data source | Granola API (remote) | Local filesystem |
| Authentication | API token | None needed |
| Async | Yes (HTTP calls) | No (local I/O) |
| Document type | Meeting transcripts | Voice recordings |
| Unique ID | document_id | directory name (timestamp) |
| Title | Meeting title | None (use datetime) |
| Content | Transcript + notes + overview | Transcription + segments |
