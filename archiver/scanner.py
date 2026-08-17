"""Scans the local superwhisper recordings directory."""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .models import ArchiverConfig, Recording, RecordingGroup, ScanResult

logger = logging.getLogger(__name__)


def is_complete(recording: Recording) -> bool:
    """Whether superwhisper has finished writing this recording.

    The recording directory and a placeholder meta.json appear within seconds
    of a recording starting; the real transcript is written into the same file
    when it ends, which for a long meeting can be an hour later. Archiving a
    placeholder would commit an empty note and mark it done forever, so an
    unfinished recording is passed over and reconsidered on a later run.
    """
    if not recording.datetime or recording.duration <= 0:
        return False
    if recording.result.strip() or recording.rawResult.strip():
        return True
    return bool(recording.segments)


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
                recording = Recording(source_dir=entry.name, **meta)
            except Exception as e:
                logger.warning(f"Failed to parse {meta_path}: {e}")
                result.failed_to_parse += 1
                continue

            if not is_complete(recording):
                logger.debug(f"Skipping {entry.name}: still recording or not yet finalised")
                result.skipped_incomplete += 1
                continue

            recordings.append(recording)

        if since:
            since_dt = datetime.fromisoformat(since)
            recordings = [r for r in recordings if datetime.fromisoformat(r.datetime) >= since_dt]

        recordings.sort(key=lambda r: r.datetime)
        result.recordings = recordings
        return result
