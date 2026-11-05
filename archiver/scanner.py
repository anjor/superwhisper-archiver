"""Scans the local superwhisper recordings directory."""

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .models import ArchiverConfig, Recording, RecordingGroup, ScanResult

logger = logging.getLogger(__name__)


# How long meta.json must sit untouched before an empty transcript is taken
# for a failure rather than for work still in progress. Transcription runs
# well after the audio stops — a long meeting has been observed finishing 16
# minutes later — so the wait is generous. The archiver runs every 15 minutes,
# so waiting costs nothing but the delay. It is also how long a meeting waits
# for a summary that never comes.
TRANSCRIPTION_GRACE_SECONDS = 7200

# How long meta.json must sit untouched before the transcript of a recording
# that is not a meeting is taken for the final one. superwhisper writes those
# transcripts once, at the end, so this is a precaution: should a later version
# write them as it goes, as 3.0 does for meetings, a note is still not cut
# short. With a 15-minute schedule it delays a note by at most one run.
SETTLE_SECONDS = 600


def has_transcript(recording: Recording) -> bool:
    """Whether superwhisper produced any transcript content for a recording."""
    return recording.has_transcript


def transcription_failed(
    recording: Recording,
    now: Optional[float] = None,
    grace_seconds: int = TRANSCRIPTION_GRACE_SECONDS,
) -> bool:
    """Whether superwhisper finished this recording but transcribed nothing.

    A recording that ends with an empty transcript looks exactly like one
    still being written: no result, no segments. The difference is that
    superwhisper keeps touching meta.json while a recording is live, so once
    the file has been untouched for the grace period and the transcript is
    still empty, no transcript is coming.

    Treating the two as the same state is how a finished meeting gets retried
    forever and never archived.
    """
    if not recording.datetime or recording.duration <= 0:
        return False
    if has_transcript(recording):
        return False
    if now is None:
        now = time.time()
    return (now - recording.meta_mtime) > grace_seconds


def is_complete(
    recording: Recording,
    now: Optional[float] = None,
    grace_seconds: int = TRANSCRIPTION_GRACE_SECONDS,
    settle_seconds: int = SETTLE_SECONDS,
) -> bool:
    """Whether superwhisper is done with this recording, one way or another.

    The recording directory and a meta.json appear within seconds of a
    recording starting. superwhisper 2.x left the transcript empty until the
    end; 3.0 fills it in as a meeting goes. Either way, archiving early would
    commit a partial note and mark it done forever, so an unfinished recording
    is passed over and reconsidered on a later run.

    A meeting is finished once superwhisper has written its summary
    (``llmResult``), which it does only in the final meta.json, seconds after
    the meeting ends. How long the file has gone unchanged proves nothing for a
    meeting, which can go quiet for longer than any settle period. Should the
    summary never come, the meeting is archived without it after
    ``grace_seconds``. Any other recording is finished once meta.json has
    stopped changing for ``settle_seconds``.

    "Done" includes a transcription that came back empty and is never going to
    fill in. That is a terminal state, and admitting it is what keeps the
    recording from being retried forever — see ``transcription_failed``.
    """
    if not recording.datetime or recording.duration <= 0:
        return False
    if now is None:
        now = time.time()
    if not has_transcript(recording):
        return transcription_failed(recording, now=now, grace_seconds=grace_seconds)
    if recording.kind == "meeting":
        return recording.llmResult is not None or (now - recording.meta_mtime) > grace_seconds
    return (now - recording.meta_mtime) > settle_seconds


def find_audio_file(recording_dir: Path) -> Optional[str]:
    """The name of the audio superwhisper kept for a recording, if any.

    2.x saved ``output.wav`` and 3.0 saves ``output.ogg``; rather than chase
    the format, take whichever ``output.*`` is actually there.
    """
    names = sorted(p.name for p in recording_dir.glob("output.*") if p.is_file())
    return names[0] if names else None


def group_recordings(
    recordings: List[Recording],
    grouping: ArchiverConfig.GroupingConfig,
) -> List[RecordingGroup]:
    """Collect recordings that belong to the same conversation.

    Recordings are grouped within a mode only, and split wherever the silence
    between one ending and the next starting exceeds that mode's gap. Ordering
    within a group, and of the groups themselves, is by start time.
    """
    by_mode: Dict[str, List[Recording]] = defaultdict(list)
    for recording in recordings:
        by_mode[recording.modeName.lower()].append(recording)

    groups: List[RecordingGroup] = []

    for mode, mode_recordings in by_mode.items():
        gap = timedelta(seconds=grouping.gap_for(mode))
        mode_recordings.sort(key=lambda r: r.datetime)

        current: List[Recording] = []
        for recording in mode_recordings:
            if current:
                previous = current[-1]
                previous_end = datetime.fromisoformat(previous.datetime) + timedelta(
                    milliseconds=previous.duration
                )
                if datetime.fromisoformat(recording.datetime) - previous_end > gap:
                    groups.append(RecordingGroup(recordings=current))
                    current = []
            current.append(recording)

        if current:
            groups.append(RecordingGroup(recordings=current))

    groups.sort(key=lambda g: g.datetime)
    return groups


def qualifies(group: RecordingGroup, filters: ArchiverConfig.FiltersConfig) -> bool:
    """Whether a group of recordings is a meeting worth archiving.

    Duration is the group total, so a conversation split into chunks is judged
    as the conversation it is rather than as its individual fragments.

    See ``ArchiverConfig.FiltersConfig`` for the two rules.
    """
    mode = group.modeName.lower()

    if mode in {m.lower() for m in filters.modes}:
        if group.duration >= filters.min_duration_ms:
            return True

    if mode in {m.lower() for m in filters.long_recording_modes}:
        if group.duration >= filters.long_recording_min_duration_ms:
            return True

    return False


class Scanner:
    """Scans superwhisper recordings directory and parses meta.json files."""

    def __init__(self, recordings_path: str):
        self.recordings_path = Path(recordings_path)

    def scan(self, since: Optional[str] = None) -> ScanResult:
        """Find every finished recording on disk.

        The whole directory is scanned every time, and archived recordings are
        deliberately *not* excluded here — grouping needs to see them, so that
        a recording finishing next to an already-archived one extends that
        note instead of starting a second one. Deduplication happens per
        group, once the groups are known.

        There is equally no "only look at recordings newer than the last run"
        watermark: a recording that is mid-flight, or that failed to archive,
        must stay visible to later runs.

        Args:
            since: Optional manual floor on recording datetime (ISO string).

        Returns:
            A ScanResult whose recordings are sorted by datetime ascending.
        """
        result = ScanResult()

        if not self.recordings_path.exists():
            logger.warning(f"Recordings path does not exist: {self.recordings_path}")
            return result

        recordings: List[Recording] = []

        for entry in self.recordings_path.iterdir():
            if not entry.is_dir():
                continue

            meta_path = entry / "meta.json"
            if not meta_path.exists():
                logger.debug(f"Skipping {entry.name}: no meta.json")
                continue

            try:
                meta = json.loads(meta_path.read_text())
                meta.pop("meta_mtime", None)
                meta.pop("audio_file", None)
                recording = Recording(
                    source_dir=entry.name,
                    meta_mtime=meta_path.stat().st_mtime,
                    audio_file=find_audio_file(entry),
                    **meta,
                )
            except Exception as e:
                logger.warning(f"Failed to parse {meta_path}: {e}")
                result.failed_to_parse += 1
                continue

            if not is_complete(recording):
                logger.debug(f"Skipping {entry.name}: still recording or not yet finalised")
                result.skipped_incomplete += 1
                continue

            if not has_transcript(recording):
                logger.warning(
                    f"{entry.name}: superwhisper finished a "
                    f"{recording.duration // 60000}m recording but transcribed nothing; "
                    f"archiving it as a failed transcription"
                )
                result.transcription_failed += 1

            recordings.append(recording)

        if since:
            since_dt = datetime.fromisoformat(since)
            recordings = [r for r in recordings if datetime.fromisoformat(r.datetime) >= since_dt]

        recordings.sort(key=lambda r: r.datetime)
        result.recordings = recordings
        return result
