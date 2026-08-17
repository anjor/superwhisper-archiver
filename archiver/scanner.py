"""Scans the local superwhisper recordings directory."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Set

from .models import ArchiverConfig, Recording, ScanResult

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


def qualifies(recording: Recording, filters: ArchiverConfig.FiltersConfig) -> bool:
    """Whether a finished recording is a meeting worth archiving.

    See ``ArchiverConfig.FiltersConfig`` for the two rules.
    """
    mode = recording.modeName.lower()

    if mode in {m.lower() for m in filters.modes}:
        if recording.duration >= filters.min_duration_ms:
            return True

    if mode in {m.lower() for m in filters.long_recording_modes}:
        if recording.duration >= filters.long_recording_min_duration_ms:
            return True

    return False


class Scanner:
    """Scans superwhisper recordings directory and parses meta.json files."""

    def __init__(self, recordings_path: str):
        self.recordings_path = Path(recordings_path)

    def scan(
        self,
        filters: Optional[ArchiverConfig.FiltersConfig] = None,
        since: Optional[str] = None,
        skip_source_dirs: Optional[Iterable[str]] = None,
    ) -> ScanResult:
        """Find recordings that are ready to be archived.

        The whole directory is scanned every time. There is deliberately no
        "only look at recordings newer than the last run" watermark: a
        recording that is mid-flight, or that failed to archive, must stay
        visible to later runs. Deduplication is ``skip_source_dirs`` alone.

        Args:
            filters: Capture rule. None means accept every finished recording.
            since: Optional manual floor on recording datetime (ISO string).
            skip_source_dirs: Directory names that are already archived.

        Returns:
            A ScanResult whose recordings are sorted by datetime ascending.
        """
        result = ScanResult()
        already_archived: Set[str] = set(skip_source_dirs or ())

        if not self.recordings_path.exists():
            logger.warning(f"Recordings path does not exist: {self.recordings_path}")
            return result

        recordings: List[Recording] = []

        for entry in self.recordings_path.iterdir():
            if not entry.is_dir():
                continue

            # Cheapest check first: skip reading meta.json entirely for
            # recordings that have already been archived.
            if entry.name in already_archived:
                result.skipped_archived += 1
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

            if filters is not None and not qualifies(recording, filters):
                result.skipped_filtered += 1
                continue

            recordings.append(recording)

        if since:
            since_dt = datetime.fromisoformat(since)
            recordings = [r for r in recordings if datetime.fromisoformat(r.datetime) >= since_dt]

        recordings.sort(key=lambda r: r.datetime)
        result.recordings = recordings
        return result
