# Automatic meeting capture — design

**Date:** 2026-08-17
**Status:** approved, not yet implemented
**Branch:** `feat/auto-capture-meetings`

## Problem

Granola archiving died on 2026-08-05 when a desktop update encrypted the local
credential store. The supported replacement is Granola's public API, which
requires a paid plan. Unattended meeting archiving has been dead since.

Superwhisper can fill the gap. Its Meeting mode captures system audio via
ScreenCaptureKit, so it hears the far end of a call without a virtual audio
driver, and `superwhisper-archiver` already scans its output and commits
markdown to git on an hourly launchd job.

The missing piece is a trigger. Nothing starts a Meeting-mode recording unless a
human presses a key, and that lapsed in February after thirteen recordings.

## What was verified before designing

Facts established by direct testing on superwhisper 2.17.0, not assumed:

- **Meeting mode works.** A manual hotkey recording produced
  `modeName: "Meeting"`, `systemAudioEnabled: true`, `duration: 6647`, a clean
  transcript, and timestamped `segments`.
- **System audio capture works.** Waveform analysis of a captured `output.wav`
  showed 16 kHz mono with amplitude spikes to 23,500 exactly during synthetic
  speech played through the output device, against a 500–1500 noise floor.
- **The URL scheme is not a usable trigger.** `superwhisper://mode?key=<key>` is
  reliable (4/4). `record` worked 2/4 and silently did nothing otherwise;
  `stop` failed to stop a recording for 60 seconds; `start` never worked at all;
  `cancel` appeared to discard and then materialised data later. URL-triggered
  recordings came back `duration: 0`, `result: ""` three times in a row despite
  holding real audio — captured, then dropped without transcription.
- **Long recordings transcribe fine** — an 11-minute Super-mode capture was
  clean. But no Meeting-mode recording longer than ~30 seconds has ever been
  tested. See Risks.
- **Diarization is off.** `meeting.json` has `diarize: false`, so `speakers` came
  back `[]`.

The consequence: `mode` comes from the URL scheme, but start/stop must
synthesise the ⌥Space hotkey — the path the UI itself uses, and the only path
that reliably produces a transcribed recording.

## Goals

Capture and archive both scheduled and ad-hoc calls (Slack huddles included)
without human action, into `granola-notes` alongside the existing Granola
archive, with speaker labels, and alert when the pipeline breaks.

## Non-goals for v0

- **Calendar enrichment.** No `attendees` frontmatter, no calendar-derived
  titles. Titles come from the transcript via the mode's LLM step. Deferred
  because Google Calendar is not synced to macOS (`~/Library/Calendars/` is
  empty), so it needs either a GUI account setup or OAuth credentials for a
  daemon — and a fresh credential dependency is exactly what broke last time.
- Realtime or streaming transcription.
- Any change to how Granola documents are archived.

## Architecture

```
callwatch daemon  (launchd KeepAlive, tick every 10s)
   │
   ├─ swhelper mic ──> bundle IDs currently capturing audio input
   │
   ├─ reconcile(state, mic_holders, now) ──> START | STOP | NOTHING
   │
   ├─ START: save activeModeKey → superwhisper://mode?key=meeting
   │         → swhelper toggle
   └─ STOP:  swhelper toggle → restore saved activeModeKey
              │
              ▼
     superwhisper writes recordings/<epoch>/{meta.json,output.wav}
              │
              ▼
     existing hourly archiver ──> granola-notes (git commit + push)
```

### The reconciler

The core insight is that the microphone holder list answers **two** questions at
once, which makes this a closed loop rather than fire-and-forget:

```python
desired = bool(call_apps & mic_holders)          # a call is happening
actual  = "com.superduper.superwhisper" in mic_holders   # we are recording
```

Meeting mode records the mic as well as system audio — the user's own voice is
in the February recordings — so superwhisper appears in the holder list while
recording. That gives us:

- **Verification.** If we send START and `actual` stays false, the keystroke did
  not land. Retry, then alert. Without this the daemon cannot tell a working
  system from a silently broken one.
- **User-override detection.** If `actual` flips false while `desired` is still
  true, the user pressed ⌥Space themselves. Do not restart — that would produce
  a second fragment file for one meeting. Latch an override flag until the call
  ends.

This assumption (superwhisper holds the mic in Meeting mode) must be confirmed
with `swhelper mic` as the first implementation step. If false, recording state
has to be tracked by watching for a new recordings directory instead, which is
weaker but workable.

### No entry debounce — filter on duration instead

The obvious design debounces the mic signal for ~15s to avoid triggering on
Zoom's mic test or a stray blip. But that discards the first 15 seconds of every
meeting, which is where the agenda gets set.

Instead: **start immediately, filter later.** Recordings shorter than
`min_duration_ms` (90s) are skipped by the archiver, which already has that
filter — it is currently set to 0. False positives cost a stray file on disk;
they cost no audio. Strictly better than a debounce.

Exit needs a grace period regardless: 60s of continued recording after the mic
is released, so a network blip or app restart mid-call does not split one
meeting into two files. The cost is 60s of trailing silence per recording.

### Timers and caps

| Parameter | Value | Why |
|---|---|---|
| tick interval | 10s | worst-case 10s of a call's opening lost |
| exit grace | 60s | survive brief mic release; costs trailing silence |
| min duration | 90s | drops mic-test blips and stray triggers |
| hard cap | 3h | a missed stop must never record forever |
| start retries | 3 ticks | then alert; a silent no-op is the failure to avoid |

### Components

**`swhelper`** — one Swift binary, two subcommands. `mic` enumerates audio
processes via `kAudioHardwarePropertyProcessObjectList`, filters on
`kAudioProcessPropertyIsRunningInput`, and prints bundle IDs as JSON. `toggle`
posts ⌥Space via `CGEvent` (keyCode 49, `.maskAlternate`).

Swift because the CoreAudio process API is C with no Python binding. One binary
rather than two so Accessibility permission is granted once.

**`callwatch`** — Python daemon in this repo, launchd `KeepAlive: true`. Holds
the reconciler and the state machine. Persists state to SQLite (`watch_state`:
state, since, recording_started_at, saved_mode_key, override_latched) so a
daemon restart mid-meeting does not lose track of an in-flight recording.

**Superwhisper config** — `modes/meeting.json`: `diarize: true`, and a prompt
that emits a title line so the archiver can derive a filename slug.
`settings/settings.json` `vocabulary`: add "Anjor" (currently transcribed
"Angel") and frequent colleague and company names.

**Archiver changes** — `min_duration_ms: 90000`; destination repo
`granola-notes`; speaker-labelled transcript rendering from `segments` +
`speakers`; run-level failure alerting; git lock retry.

## Archive format

Consolidating into `granola-notes` means adopting its conventions:
`YYYY/MM/YYYY-MM-DD-<slug>.md`, slug derived from the LLM-generated title.
Same-day slug collisions get a `-2` suffix.

Frontmatter mirrors the Granola notes where the fields carry the same meaning
and drops what is Granola-specific (`document_id`, `workspace_id`):

```yaml
title: ...
date: 2026-08-17
source: superwhisper        # provenance, since two archivers write here now
recording_id: "1786960264"  # superwhisper recordings/<epoch>
duration_ms: 6647
created_at: ...
archived_at: ...
speakers: [...]             # empty until diarization is confirmed working
```

`source:` matters: with two archivers writing to one repo, provenance must be
visible in the file, not inferred from the commit.

## Concurrency with granola-archiver

Both archivers will commit and push to `granola-notes` — this one hourly, that
one every 30 minutes. They will collide on the git index lock.

`granola-archiver` already has stale-lock recovery (commit `7dffec7`). The same
handling is needed here: pull-before-push, retry on lock contention, and never
leave a partial commit. **This needs agreeing with the parallel consolidation
work in `granola-archiver` rather than being solved twice.**

## Failure modes and alerting

The lesson of the six-day Granola outage was not that it broke — it is that it
broke *quietly*, because the only alerting path watched a document retry queue
that stayed empty when auth failed before any document was enqueued.

This pipeline has the same shape, so it gets the same treatment: port
`run_health.py` from `granola-archiver` (single-row table, alert on first
failure then at most once per 6h). Conditions that must alert:

- START sent, `actual` never became true (keystroke not landing — most likely
  cause: Accessibility permission revoked)
- hard cap reached (a stop was missed)
- recording finished with `duration: 0` or empty `result` (the URL-trigger
  failure mode; if it appears via the hotkey path too, something is wrong)
- archiver run failed outright
- daemon not running (launchd `KeepAlive` should prevent it; alert if the state
  row goes stale)

## Testing

`reconcile()` is a pure function of `(state, mic_holders, now)`, so the entire
trigger logic is testable without audio, meetings, or waiting. That is where the
tests concentrate:

- call starts → START; call ends → grace → STOP
- mic released and re-acquired inside the grace window → no STOP, one file
- superwhisper alone in the holder list (plain dictation) → NOTHING
- START sent but `actual` stays false → retry, then alert
- `actual` drops while `desired` holds → override latched, no restart
- hard cap forces STOP
- state survives a simulated daemon restart mid-recording

Also: markdown formatter against a fixture `meta.json` with speakers; slug
derivation and collision handling; `swhelper mic` JSON shape.

End-to-end is manual: a real Slack huddle, then a real Zoom call.

## Risks

**Long Meeting-mode recordings are untested.** Nothing longer than ~30 seconds
has ever been captured in Meeting mode. A 60-minute recording is roughly 115 MB
of 16 kHz WAV going to superwhisper's cloud, and the failure behaviour is
unknown. **Test with ten minutes of synthetic audio before building anything
else** — if this fails, superwhisper is only viable as a recorder and
transcription moves to local whisper.cpp.

**Diarization is unproven.** `diarize: true` has never been exercised here, and
the shape of a populated `speakers` array is unknown. Capture one diarized
recording and inspect it before writing the formatter against a guess.

**⌥Space collides with dictation.** Pressing it mid-meeting stops the meeting
recording. The override latch prevents fragment files but does not prevent the
lost audio. Worth investigating whether superwhisper supports a per-mode hotkey,
which would remove the collision entirely.

**Accessibility permission is revocable** and updates can reset it. Hence the
verification loop and its alert.

**Mode restore races the user.** The daemon saves and restores `activeModeKey`
around a recording. If the user switches mode mid-meeting, restore overwrites
their choice. Minor, but restore should only fire if the current mode is still
`meeting`.

**Ad-hoc capture is a scope expansion.** Silently recording impromptu huddles
goes beyond scheduled calls. Accepted deliberately: Granola behaved the same
way.

## Open questions

1. Does superwhisper hold the mic while recording in Meeting mode? Gates the
   reconciler design. Answer first.
2. Does a per-mode hotkey exist, avoiding the ⌥Space collision?
3. How should the git-lock strategy be shared with `granola-archiver` rather
   than implemented twice?
