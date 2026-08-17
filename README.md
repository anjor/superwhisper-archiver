# superwhisper-archiver

Archive superwhisper meeting recordings as markdown to a git repository.

Scans `~/Documents/superwhisper/recordings`, formats each qualifying recording
as markdown with YAML frontmatter, and commits it to a notes repo on a
schedule.

## Usage

```sh
uv run python -m archiver              # archive everything not yet archived
uv run python -m archiver --dry-run    # show what would be archived
uv run python -m archiver --since 2026-02-01
uv run python -m archiver --modes meeting,super
```

Config is looked up in this order: `--config`, `$SUPERWHISPER_ARCHIVER_CONFIG`,
`~/.config/superwhisper-archiver/config.yaml`, `./config.yaml`.

## What gets archived

Two independent rules, either of which admits a recording:

- a mode in `filters.modes` lasting at least `filters.min_duration_ms`
- a mode in `filters.long_recording_modes` lasting at least
  `filters.long_recording_min_duration_ms`

The second rule exists because long mic-only conversations get recorded in a
dictation mode; they are meetings in everything but the mode they were captured
with. The duration floors keep accidental sub-second taps out of the archive.

## One note per conversation, not per recording

Stopping and restarting a recording starts a new superwhisper directory, so a
single call routinely arrives as several recordings seconds apart. Recordings
in the same mode are grouped when the silence between one ending and the next
starting is within that mode's `grouping.gap_seconds`, and the capture rule is
applied to the **group total**. Without this a call split into chunks loses its
opening minutes, because each fragment is measured against the duration floor
on its own.

Gaps are per mode because the modes need opposite things. Meetings are rare and
never adjacent, so they take a generous gap; dictation modes need a tight one,
or a burst of unrelated snippets adds up past the long-recording floor and
masquerades as a meeting.

A group is identified by its earliest recording, so a late arrival rewrites the
same note in place. If regrouping does move a note, the superseded file is
deleted in the same commit rather than left orphaned.

Notes for a single recording keep the singular `source_dir` key and render as
they always did. Merged notes carry `source_dirs` and `recording_count`, label
each part, and offset segment timings so they run continuously across parts.

## No timestamp watermark, by design

Every run scans the entire recordings directory. Deduplication is the
`archived_recordings` table alone — never "only look at recordings newer than
the last run".

This matters because superwhisper creates the recording directory and writes a
placeholder `meta.json` within seconds of a recording starting, then rewrites
that same file with the real transcript when the recording ends — which for a
long meeting can be an hour later. Anything that scans by recency sees the
placeholder, skips it, and then never looks at that recording again. An earlier
version of this archiver worked exactly that way and silently lost recordings,
including two meetings over half an hour long.

So: a recording that is still in flight is passed over by `scanner.is_complete`
and reconsidered on the next run, and a recording that fails to commit simply
stays out of `archived_recordings` and is retried. Neither case needs a retry
queue, and neither can fall off the end of a window.

Scanning also does not exclude already-archived recordings — grouping needs to
see them, or a recording finishing next to an archived one would open a second
note instead of joining the existing one. Deduplication happens per group: a
group is done only when every one of its recordings is.

Recording timestamps in `meta.json` are UTC and are stored as-is.

## Failure alerting

Failures are counted in `failed_recordings`. Once a recording has failed
`ALERT_ATTEMPT_THRESHOLD` (3) runs in a row, a macOS notification fires, so a
persistently broken archiver cannot fail quietly for days.

## Development

```sh
uv run pytest tests/ -v
```
