# Automatic meeting capture — design

**Date:** 2026-08-17 (revised same day)
**Status:** step 1 verified 2026-09-01; steps 2–5 outstanding
**Branch:** `feat/meeting-auto-capture-trigger`, cut from
`fix/watermark-data-loss-and-granola-cutover`

## Problem

Granola archiving died on 2026-08-05 when a desktop update encrypted the local
credential store. The supported replacement needs a paid plan. Superwhisper's
Meeting mode captures system audio via ScreenCaptureKit, so it hears the far end
of a call without a virtual audio driver, and `superwhisper-archiver` commits
markdown to git on an hourly launchd job.

The missing piece is a trigger. Nothing starts a Meeting-mode recording unless a
human presses a key, and that lapsed in February after thirteen recordings.

## Correction to the first draft of this document

The first version of this spec claimed that URL-triggered recordings "come back
`duration: 0`, `result: ""` — captured, then dropped without transcription."
**That was wrong**, and `154b5fb` explains why: superwhisper writes a
*placeholder* `meta.json` seconds into a recording and only fills in the
transcript when the recording ends. Every empty result observed during testing
was a placeholder read while the recording was still running.

The coherent reading of that testing is different and more useful:

- `superwhisper://record` **does** start a recording.
- `superwhisper://stop` and `cancel` do **not** reliably end one — a recording
  stopped at ~7s produced a 60-second WAV.
- Because recordings kept running, later `record` calls were no-ops against an
  already-recording app. That, not flakiness in `record`, is why it appeared to
  work only 2 out of 4 times.
- `superwhisper://start` never created a recording. `mode?key=` is reliable (4/4).

So the design needs a working **stop**, and start may well be fine over the URL
scheme. Both should be verified directly before the daemon is built; see
Implementation order.

## Step 1 settled — probed 2026-09-01 on superwhisper 2.17.3

`swhelper mic` exists now, and watching the mic while driving the URL scheme
answers the three questions the daemon rests on:

| Question | Answer |
|---|---|
| Does superwhisper hold the mic while recording? | **Yes** — appears ~1.3s after `record` |
| Does `superwhisper://record` start a recording? | **Yes** |
| Does `superwhisper://stop` end one? | **No** — mic still held after 60s |
| Does `superwhisper://cancel` end one? | **No** |
| Does the ⌥Space hotkey end one? | **Yes** — mic released within 2s |

The 25-second probe ran for **238 seconds**, ending only when `swhelper toggle`
pressed the hotkey. That is the "forgot to switch it off" failure reproduced
deliberately, and it confirms the first draft's suspicion about `stop`.

Three consequences for the design:

- **The daemon must use the hotkey to stop**, not the URL scheme. `record` over
  the URL scheme is fine for START; STOP is `swhelper toggle`.
- **Accessibility moves onto the critical path.** It was written up as a
  fallback risk; it is now load-bearing for every stop. The verification loop
  and its alert are what keep a revoked permission from silently recording
  forever — and, per the 3h hard cap, that is not a hypothetical.
- **The verification loop works as designed.** `actual` is observable, so START
  and STOP can both be checked rather than assumed.

`com.apple.replayd` also appears alongside superwhisper during Meeting mode —
that is ScreenCaptureKit taking system audio, a second confirmation that a
capture is really running and not just the mic being open.

### swhelper as built

`mic` prints the bundle IDs holding audio input as a JSON array, falling back to
the executable name for processes without a bundle ID, so an unidentifiable mic
holder still shows up in the log. `mic --detail` dumps every audio process with
pid, name and input/output state, which is what the probe used. `toggle` posts
the record hotkey, read from superwhisper's own `KeyboardShortcuts_toggleRecording`
preference rather than hardcoded, so a rebind does not silently break the daemon;
`toggle --check` reports the resolved hotkey and whether Accessibility is granted
without pressing anything.

Toggling is blind — it starts if stopped and stops if started — so the
reconciler must read `mic` before and after rather than trusting the press.

**Build note.** `swiftc` is resolved explicitly by `build.sh`, not taken off
PATH: a half-updated Xcode.app can leave `swift`, `swiftc` and `xcodebuild`
failing to load (`libxcodebuildLoader.dylib: Symbol not found: _XPCTypeBool`)
while the CommandLineTools toolchain beside it works. Each compiler is paired
with its own SDK because the CLT `swiftc` cannot find the standard library
otherwise.

### Still open after step 1

- `swhelper` inherits the Accessibility grant of whoever launches it. It ran
  trusted from a terminal that already had the permission; **under launchd it
  will need its own grant**, which has to be confirmed when the daemon is
  installed.
- `diarize` is still `false` in `~/Documents/superwhisper/modes/meeting.json`.
  The renderer from `40e4c57` is shipped but nothing produces `speakers` yet, so
  design step 2 is not actually done.

## What is verified

On superwhisper 2.17.0, by direct testing:

- **Meeting mode works.** A manual hotkey recording gave `modeName: "Meeting"`,
  `systemAudioEnabled: true`, `duration: 6647`, a clean transcript, timestamped
  `segments`.
- **System audio capture works.** Waveform analysis of a captured `output.wav`
  showed 16 kHz mono with amplitude spikes to 23,500 exactly during synthetic
  speech played through the output device, against a 500–1500 noise floor.
- **Long recordings work.** `154b5fb` recovered meetings of 33 and 77 minutes,
  and a 5m50s Meeting-mode capture archived cleanly on 2026-08-17. This retires
  the "long recordings are untested" risk from the first draft.
- **Diarization is off.** `meeting.json` has `diarize: false`, so `speakers`
  comes back `[]`.

## Scope after `154b5fb`

That commit did substantially more than retarget the archive, and it removes
several items from this design. What is **already done**:

- Watermark deleted; dedup is the archived set alone, so in-flight recordings and
  failed commits are self-healing
- `scanner.is_complete` gates placeholder metadata
- `qualifies()` as a pure capture rule: Meeting mode ≥ 60s, plus long
  dictation-mode recordings ≥ 300s
- Archive retargeted at `granola-notes`
- Stale `index.lock` recovery — this answers the git-contention question the
  first draft raised as an open item
- Per-recording alerting after three failed runs; XDG config; anchored state DB

What **remains**, and is the whole of this design:

1. The trigger — `swhelper` + `callwatch` (below)
2. Diarization: `diarize: true`, and rendering speaker-labelled transcripts
3. Vocabulary: "Anjor" is transcribed "Angel"
4. Titles — see Archive format
5. Run-level failure alerting — see Alerting

## Goals

Capture both scheduled and ad-hoc calls (Slack huddles included) without human
action, with speaker labels, and alert when the trigger breaks.

## Non-goals for v0

- **Calendar enrichment.** No `attendees`, no calendar-derived titles. Google
  Calendar is not synced to macOS (`~/Library/Calendars/` is empty), so it needs
  either a GUI account setup or OAuth credentials for a daemon — and a fresh
  credential dependency is what broke Granola.
- Realtime transcription; any change to Granola document archiving.

## Architecture

```
callwatch daemon  (launchd KeepAlive, tick every 10s)
   │
   ├─ swhelper mic ──> bundle IDs currently capturing audio input
   │
   ├─ reconcile(state, mic_holders, now) ──> START | STOP | NOTHING
   │
   ├─ START: save activeModeKey → superwhisper://mode?key=meeting → start
   └─ STOP:  stop → restore saved activeModeKey
              │
              ▼
     superwhisper writes recordings/<epoch>/{meta.json,output.wav}
              │
              ▼
     existing hourly archiver ──> granola-notes
```

### The reconciler

The microphone holder list answers **two** questions, which makes this a closed
loop rather than fire-and-forget:

```python
desired = bool(call_apps & mic_holders)                   # a call is happening
actual  = "com.superduper.superwhisper" in mic_holders    # we are recording
```

Meeting mode records the mic as well as system audio — the user's own voice is in
the February recordings — so superwhisper should appear in the holder list while
recording. That gives:

- **Verification.** If START is sent and `actual` stays false, the action did not
  land. Retry, then alert. Without this the daemon cannot distinguish a working
  system from a silently broken one — the exact failure that cost six days on
  Granola.
- **User-override detection.** If `actual` drops while `desired` holds, the user
  stopped the recording by hand. Latch an override and do not restart, or one
  meeting becomes two fragment files.

This assumption must be confirmed with `swhelper mic` first. If false, recording
state has to be inferred from a new recordings directory appearing, which is
weaker but workable.

### No entry debounce — filter on duration instead

Debouncing the mic signal ~15s to ignore Zoom's mic test would discard the first
15 seconds of every meeting, where the agenda gets set. Instead **start
immediately and filter later**: the shipped `qualifies()` already drops Meeting
captures under 60s. A false trigger costs a stray file, not lost audio.

Exit still needs a grace period: 60s of continued recording after the mic is
released, so a blip or app restart mid-call does not split one meeting in two.
The cost is 60s of trailing silence.

### Timers

| Parameter | Value | Why |
|---|---|---|
| tick interval | 10s | worst case 10s of a call's opening lost |
| exit grace | 60s | survive brief mic release; costs trailing silence |
| min duration | 60s | already shipped in `qualifies()`; drops mic-test blips |
| hard cap | 3h | a missed stop must never record forever |
| start retries | 3 ticks | then alert; a silent no-op is the failure to avoid |

### Components

**`swhelper`** — one Swift binary, two subcommands. `mic` enumerates audio
processes via `kAudioHardwarePropertyProcessObjectList`, filters on
`kAudioProcessPropertyIsRunningInput`, prints bundle IDs as JSON. `toggle` posts
⌥Space via `CGEvent` (keyCode 49, `.maskAlternate`) — needed only if the URL
scheme cannot stop a recording. Swift because the CoreAudio process API is C with
no Python binding; one binary so Accessibility is granted once.

**`callwatch`** — Python daemon in this repo, launchd `KeepAlive: true`. Holds
the reconciler. Persists to SQLite (`watch_state`: state, since,
recording_started_at, saved_mode_key, override_latched) so a restart mid-meeting
does not lose an in-flight recording.

## Archive format

`granola-notes` now holds two conventions, and they do not agree:

| | Granola | superwhisper |
|---|---|---|
| filename | `2026-08-13-anjorben.md` | `2026-08-17-10-15-12.md` |
| frontmatter | `title`, `date`, `attendees`, `creator` | `datetime`, `mode`, `duration_ms`, `model`, `source_dir` |
| heading | `# Anjor/Ben` | `# Recording — 2026-08-17 10:15` |

The superwhisper side has no title, which makes the archive hard to browse — the
2026-08-17 10:15 note is a real conversation about the FDE model and Palantir,
filed under a timestamp. Proposal: extend the Meeting mode prompt to emit a title
line, derive the filename slug from it, and add `title` to the frontmatter,
converging on the Granola convention. This changes shipped behaviour, so it needs
agreeing rather than assuming.

Diarization matters for the same reason: that note is one undivided wall of text
with two speakers in it, and no way to tell who said what.

## Alerting

The shipped alerting is per-recording — `maybe_alert_failures` over recordings
that failed three runs, called after the scan. That is the same shape as
granola-archiver's original alerting, which could not catch the outage that
started this work, because the failure happened before anything was enqueued.

Note the watermark deletion already removes the *data-loss* half of the risk:
nothing is silently dropped, and a zero-archived run is now legitimate, so zero
cannot be alerted on. What remains uncovered is a run that dies outright.

Port `run_health.py` from granola-archiver (`fix/alert-on-run-level-failures`,
single-row table, alert on first failure then at most once per 6h). Conditions
that must alert:

- START sent, `actual` never became true — most likely Accessibility revoked
- hard cap reached (a stop was missed)
- archiver or daemon run failed outright
- daemon state row gone stale (`KeepAlive` should prevent it; alert if not)

## Testing

`reconcile()` is a pure function of `(state, mic_holders, now)`, so the trigger
logic is fully testable without audio, meetings, or waiting:

- call starts → START; call ends → grace → STOP
- mic released and re-acquired inside grace → no STOP, one file
- superwhisper alone in the holder list (plain dictation) → NOTHING
- START sent but `actual` stays false → retry, then alert
- `actual` drops while `desired` holds → override latched, no restart
- hard cap forces STOP
- state survives a simulated daemon restart mid-recording

Plus: speaker-labelled rendering against a fixture `meta.json`; slug derivation
and same-day collisions; `swhelper mic` JSON shape. End-to-end is manual — a real
Slack huddle, then a real Zoom call.

## Implementation order

1. ~~**Settle start/stop.**~~ **Done 2026-09-01** — see "Step 1 settled" above.
   START is `superwhisper://record`; STOP is `swhelper toggle`, because the URL
   scheme cannot stop a recording. superwhisper does hold the mic while
   recording, so the verification loop is viable.
2. Enable `diarize: true`, capture one real meeting, inspect the `speakers`
   shape before writing the formatter against a guess.
3. `reconcile()` and its tests.
4. `callwatch` daemon, launchd job, run-level alerting.
5. Titles and slug convention, if agreed.

## Risks

**⌥Space collides with dictation.** The hotkey path is not a maybe any more —
step 1 settled that it is the only working stop. Pressing it mid-meeting stops
the recording; the override latch prevents fragment files but not the lost
audio. Check whether superwhisper supports a per-mode hotkey.

**Accessibility permission is revocable** and updates can reset it — hence the
verification loop and its alert.

**Mode restore races the user.** Restore should fire only if the current mode is
still `meeting`, or it overwrites a mid-meeting mode change.

**Auto-capture interacts with the long-dictation rule.** The daemon restores mode
to `super` after a meeting, and `qualifies()` archives Super-mode recordings over
5 minutes. Long private dictations will therefore be archived to a git repo. That
is the shipped behaviour and may well be intended, but auto-capture makes it
easier to hit by accident.

**Ad-hoc capture is a deliberate scope expansion.** Silently recording impromptu
huddles goes beyond scheduled calls. Accepted: Granola behaved the same way.

## Open questions

1. Does superwhisper hold the mic while recording in Meeting mode? Gates the
   reconciler. Answer first.
2. Can the URL scheme stop a recording, or is ⌥Space synthesis required?
3. Does a per-mode hotkey exist, avoiding the ⌥Space collision?
4. Converge the two note formats on titles and slugs, or leave superwhisper notes
   filed under timestamps?
