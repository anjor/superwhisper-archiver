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
