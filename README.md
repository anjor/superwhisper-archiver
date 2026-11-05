# superwhisper-archiver

Archive superwhisper meeting recordings as markdown to a git repository.

Scans `~/Documents/superwhisper/recordings`, formats each qualifying recording
as markdown with YAML frontmatter, and commits it to a notes repo on a
schedule.

## How it works

1. superwhisper (3.0 or later) detects that a meeting has started and offers
   to record it. Click **Start meeting**.
2. When the meeting ends, it offers to stop. Click **End meeting**. A few
   seconds later superwhisper writes the final transcript and a summary into
   the recording's `meta.json`.
3. Every 15 minutes the archiver picks up each finished recording it has not
   archived yet, writes it as a note in the notes repo (`archive.repo_path`,
   currently `granola-notes`, a name left over from the Granola-based
   archiver this one replaced), commits, and pushes.

So a meeting's note appears within about 20 minutes of clicking End meeting:
up to five minutes to be sure superwhisper has stopped recording, then up to
15 until the next run.

## Usage

```sh
uv run python -m archiver              # archive everything not yet archived
uv run python -m archiver --dry-run    # show what would be archived
uv run python -m archiver --since 2026-02-01
uv run python -m archiver --modes meeting,super
```

Config is looked up in this order: `--config`, `$SUPERWHISPER_ARCHIVER_CONFIG`,
`~/.config/superwhisper-archiver/config.yaml`, `./config.yaml`.

## Running it on a schedule

A launchd agent runs `uv run python -m archiver` in this checkout every 15
minutes, and once whenever it is loaded. Its definition is
[`launchd/com.anjor.superwhisper-archiver.plist`](launchd/com.anjor.superwhisper-archiver.plist).

```sh
# install
cp launchd/com.anjor.superwhisper-archiver.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.anjor.superwhisper-archiver.plist

# pause, and resume
launchctl bootout gui/$(id -u)/com.anjor.superwhisper-archiver
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.anjor.superwhisper-archiver.plist

# run now
launchctl kickstart gui/$(id -u)/com.anjor.superwhisper-archiver
```

**It runs whatever is checked out.** The agent runs the code in this
directory, so if a feature branch is checked out, that branch is what
archives your meetings. Keep this checkout on `main`.

Where things live:

- **Config:** `config.yaml` in this repo. The agent passes no `--config` and
  sets no `$SUPERWHISPER_ARCHIVER_CONFIG`, so unless
  `~/.config/superwhisper-archiver/config.yaml` exists, this is the live
  config.
- **State:** `state/archive_state.db` (git-ignored). `archived_recordings`
  records what has been archived, and `failed_recordings` what keeps failing.
- **Logs:** `/tmp/superwhisper-archiver.log`, plus the agent's own output in
  `/tmp/superwhisper-archiver-stdout.log` and
  `/tmp/superwhisper-archiver-stderr.log`.

## Configuration

`config.yaml` has five sections:

- `superwhisper.recordings_path`: where superwhisper keeps its recordings.
- `archive`: the notes repo (`repo_path`), and the remote and branch it
  pulls from and pushes to.
- `filters`: which recordings are meetings worth a note. See
  [What gets archived](#what-gets-archived).
- `grouping`: how close together recordings must be to share a note. See
  [One note per conversation](#one-note-per-conversation-not-per-recording).
- `logging`: log level and file.

## What gets archived

Two independent rules, either of which admits a recording:

- a mode in `filters.modes` lasting at least `filters.min_duration_ms`
- a mode in `filters.long_recording_modes` lasting at least
  `filters.long_recording_min_duration_ms`

The second rule exists because long mic-only conversations get recorded in a
dictation mode; they are meetings in everything but the mode they were captured
with. The duration floors keep accidental sub-second taps out of the archive.

superwhisper 3.0 records the meetings it detects in its Meeting mode, so the
`meeting` entry in `filters.modes` is what admits them.

## What a note looks like

Each note is written to `YYYY/MM/YYYY-MM-DD-HH-MM-SS.md` in the notes repo,
named after the recording's start time. Its YAML frontmatter records when the
meeting was and how long it ran, the mode, models and language, the speakers
where known, and which recording directories it came from. The body has:

- `## Transcription`: superwhisper's transcript.
- `## Summary`: superwhisper's summary of the meeting, when there is one.
- `## Conversation`: the transcript as turns, one per speaker, for diarized
  recordings. See [Diarization](#diarization).
- `## Segments`: every segment with its timestamps.

A recording whose transcription failed gets a note saying so instead. See
[When transcription comes back empty](#when-transcription-comes-back-empty).

## One note per conversation, not per recording

Stopping and restarting a recording starts a new superwhisper directory, so a
single call routinely arrives as several recordings seconds apart. Recordings
in the same mode are grouped when the silence between one ending and the next
starting is within that mode's `grouping.gap_seconds`, and the capture rule is
applied to the **group total**. Without this a call split into chunks loses its
opening minutes, because each fragment is measured against the duration floor
on its own.

**Keep the gaps tight.** A genuine restart within one call happens within
seconds — the longest observed is 6s — whereas the shortest gap between two
different back-to-back calls is over 9 minutes. A generous gap therefore buys
no tolerance for pauses; it merges unrelated meetings, splicing one call's
sign-off into the next one's hello. Dictation modes need a tight gap for a
second reason: a burst of unrelated snippets otherwise adds up past the
long-recording floor and masquerades as a meeting.

The trade-off is deliberate. If a call is genuinely paused for minutes and
resumed, it becomes two notes — which is much easier to live with than two
people's conversations silently fused into one.

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
long meeting can be an hour later. (A 3.0 meeting rewrites it all the way
through; see [Knowing when a meeting has ended](#knowing-when-a-meeting-has-ended).)
Anything that scans by recency sees the placeholder, skips it, and then never
looks at that recording again. An earlier version of this archiver worked
exactly that way and silently lost recordings, including two meetings over
half an hour long.

So: a recording that is still in flight is passed over by `scanner.is_complete`
and reconsidered on the next run, and a recording that fails to commit simply
stays out of `archived_recordings` and is retried. Neither case needs a retry
queue, and neither can fall off the end of a window.

Scanning also does not exclude already-archived recordings — grouping needs to
see them, or a recording finishing next to an archived one would open a second
note instead of joining the existing one. Deduplication happens per group: a
group is done only when every one of its recordings is.

Recording timestamps in `meta.json` are UTC and are stored as-is.

## Knowing when a meeting has ended

superwhisper 3.0 detects meetings by itself and, unlike 2.x, writes the
transcript into `meta.json` *while the meeting is still going* — duration,
text and segments grow every few seconds. A non-empty transcript therefore no
longer means a recording has ended. Treating it as if it did is how the first
3.0 meeting, 25 minutes long, was archived 11 minutes in and then never
revisited, since an archived recording is not looked at again.

What does mark the end is the summary. superwhisper writes `llmResult`, along
with the meeting's `title`, only into the final `meta.json`, a few seconds
after the meeting ends (when you click End meeting). So a meeting counts as
finished once `llmResult` is there, and is archived on the next run. How long
the file has gone unchanged is deliberately not used for meetings: a meeting
can go quiet for longer than any fixed wait, and nothing guarantees that
superwhisper touches the file while nobody speaks. If the summary never
arrives, the meeting is archived without it once `meta.json` has gone
untouched for `scanner.TRANSCRIPTION_GRACE_SECONDS` (two hours).

Recordings that are not meetings get their transcript in a single write at
the end. As a precaution they still count as finished only once `meta.json`
has gone untouched for `scanner.SETTLE_SECONDS` (10 minutes), so a change in
how superwhisper writes the file cannot reopen the same hole.

Whatever `meta.json` says, no recording counts as finished while superwhisper
is still writing its audio: the audio file (`output.ogg`, or `output.wav` from
2.x) must also have gone untouched for `scanner.AUDIO_SETTLE_SECONDS` (five
minutes). superwhisper writes the audio every 20 seconds or so while it
records, and in none of the 2,806 recordings on disk in November 2026 did it
write the audio after the final `meta.json`. So audio written in the last few
minutes means the recording is still going. This is a safeguard in case
`meta.json` ever looks final mid-recording, for example if a later version of
superwhisper writes the summary before a meeting ends. It delays a note by at
most one run.

## When transcription comes back empty

A recording can finish and still have no transcript: superwhisper writes the
real `duration` but its cloud transcription returns nothing — sometimes
literally a few spaces in `rawResult`. On disk that is indistinguishable from
a recording still in flight, and treating the two the same way is how a
finished 31-minute meeting gets skipped as "not yet finalised" on every run
forever, without ever appearing in the archive or in an error.

The tell is `meta.json`'s mtime. Once the file has sat untouched for
`scanner.TRANSCRIPTION_GRACE_SECONDS` (two hours) and the transcript is still
empty, no transcript is coming. The wait is deliberately generous:
transcription runs well after the audio stops (by 16 minutes for one observed
meeting), and nothing guarantees that superwhisper touches the file while
nobody is speaking. Since the archiver runs every 15 minutes, waiting costs
nothing but the delay.

Such a recording is then archived as a **stub note**: the usual frontmatter
plus `transcription_failed: true`, and a body saying what happened and where
the audio still is — `output.wav` from 2.x, `output.ogg` from 3.0, whichever
the recording directory actually holds. That keeps the record that the
conversation happened, lets you re-transcribe from the audio it points at,
and — because the note is committed — stops the recording being retried
forever.

Grouping makes this partial rather than all-or-nothing: a short recording that
transcribed is regularly grouped with a long one that did not. A note that
dropped the failed part silently would claim 29 minutes and show 45 seconds of
text, so failed parts are always declared, with `transcription_failed_parts: N`
in the frontmatter and the missing duration named in the body.

## Diarization

When a mode has diarization enabled, superwhisper tags each segment with a
0-based `speaker` id. Those are rendered as a `speaker_count` in the
frontmatter, a speaker prefix on each segment line, and a `## Conversation`
section that merges each speaker's consecutive segments into one turn.

Speaker ids are assigned **per recording**, so a grouped note cannot assume
Speaker 0 is the same person throughout. Each part is rendered separately with
a caveat, and `speaker_count` is the maximum across parts rather than the sum.

superwhisper 3.0 meetings also carry a `speakers` list naming each id. Where a
name is known it replaces "Speaker N" in segments and turns, and the names are
listed under `speakers:` in the frontmatter. Labels, not ids, decide turns and
`speaker_count`: the diarizer sometimes splits one person across two ids, and
those should read as one person, not two. Names identify people across parts,
so the per-part caveat is shown only when bare numbers are.

Undiarized recordings render exactly as before.

## Failure alerting

Failures are counted in `failed_recordings`. Once a recording has failed
`ALERT_ATTEMPT_THRESHOLD` (3) runs in a row, a macOS notification fires, so a
persistently broken archiver cannot fail quietly for days.

## Unused: automatic meeting capture

`archiver/reconciler.py`, `swhelper/` and
[the auto-capture design](docs/plans/2026-08-17-meeting-auto-capture-design.md)
come from an earlier plan for the archiver to start and stop superwhisper
recordings itself whenever a call was on. Nothing runs them: the archiver
does not import the reconciler, and no launchd agent starts it.
superwhisper 3.0's own meeting detection does that job now. `swhelper` can
still be built with `swhelper/build.sh`, and `swhelper mic` is a handy way to
see which apps are using the microphone.

## Development

```sh
uv run pytest tests/ -v
uv run ruff check .
```
