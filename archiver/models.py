"""Pydantic models for the superwhisper archiver."""

from typing import Dict, Optional, List
from pydantic import BaseModel, Field


class Segment(BaseModel):
    text: str
    start: float
    end: float
    # Present only when the recording's mode has diarization enabled. Speaker
    # ids are 0-based and assigned per recording, so the same id in two
    # recordings is not necessarily the same person.
    speaker: Optional[int] = None
    confidence: Optional[float] = None


class Recording(BaseModel):
    """A parsed superwhisper recording from meta.json.

    Every field except ``source_dir`` is optional. superwhisper creates the
    recording directory and writes a *placeholder* meta.json a few seconds into
    a recording, only rewriting it in place once the recording finishes. That
    placeholder is missing most fields, so a strict model would raise and the
    recording would be skipped as unparseable. Defaults let it parse, and
    ``scanner.is_complete`` decides whether it is finished yet.
    """

    source_dir: str
    datetime: str = ""
    result: str = ""
    rawResult: str = ""
    duration: int = 0  # milliseconds
    segments: List[Segment] = Field(default_factory=list)
    modeName: str = ""
    modelName: str = ""
    languageSelected: str = ""
    systemAudioEnabled: bool = False
    appVersion: str = ""
    languageModelName: Optional[str] = None
    llmResult: Optional[str] = None

    class Config:
        extra = "ignore"


class RecordingGroup(BaseModel):
    """Recordings that together make up one conversation.

    superwhisper starts a new directory every time recording is stopped and
    restarted, so a single call routinely arrives as several recordings a few
    seconds apart. Archiving each one separately splits a conversation across
    notes and — because the duration floor is applied per recording — can drop
    its opening minutes entirely. The group is the unit that gets filtered,
    formatted and archived.
    """

    recordings: List[Recording] = Field(min_length=1)

    @property
    def primary(self) -> Recording:
        """The earliest recording, which gives the group its identity."""
        return self.recordings[0]

    @property
    def source_dirs(self) -> List[str]:
        return [r.source_dir for r in self.recordings]

    @property
    def datetime(self) -> str:
        return self.primary.datetime

    @property
    def modeName(self) -> str:
        return self.primary.modeName

    @property
    def duration(self) -> int:
        """Total recorded milliseconds, excluding the gaps between parts."""
        return sum(r.duration for r in self.recordings)

    @property
    def diarized_recordings(self) -> List[Recording]:
        return [r for r in self.recordings if any(s.speaker is not None for s in r.segments)]

    @property
    def speaker_count(self) -> int:
        """Speakers in the part that heard the most of them.

        Not a sum: ids restart with each recording, so parts cannot be added
        together without claiming more speakers than were present.
        """
        return max(
            (len({s.speaker for s in r.segments if s.speaker is not None}) for r in self.recordings),
            default=0,
        )


class ArchiverConfig(BaseModel):
    """Configuration for the archiver."""

    class SuperwhisperConfig(BaseModel):
        recordings_path: str

    class ArchiveConfig(BaseModel):
        repo_path: str
        remote_name: str = "origin"
        default_branch: str = "main"

    class FiltersConfig(BaseModel):
        """Which recordings count as a meeting worth archiving.

        Two independent rules, either of which admits a recording:
        a mode in ``modes`` lasting at least ``min_duration_ms``, or a mode in
        ``long_recording_modes`` lasting at least
        ``long_recording_min_duration_ms``. The second rule catches long
        mic-only conversations recorded in a dictation mode.
        """

        modes: List[str] = Field(default_factory=lambda: ["meeting"])
        min_duration_ms: int = 60000
        long_recording_modes: List[str] = Field(default_factory=list)
        long_recording_min_duration_ms: int = 300000

    class GroupingConfig(BaseModel):
        """How close two recordings must be to count as one conversation.

        The gap is measured from the end of one recording to the start of the
        next, and is per mode: a meeting tolerates long pauses, whereas
        dictation modes need a tight gap so that a burst of unrelated snippets
        is not fused into a fake meeting.
        """

        gap_seconds: Dict[str, int] = Field(default_factory=dict)
        default_gap_seconds: int = 60

        def gap_for(self, mode: str) -> int:
            return self.gap_seconds.get(mode.lower(), self.default_gap_seconds)

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        file: str = "/tmp/superwhisper-archiver.log"

    superwhisper: SuperwhisperConfig
    archive: ArchiveConfig
    filters: FiltersConfig
    grouping: GroupingConfig = Field(default_factory=lambda: ArchiverConfig.GroupingConfig())
    logging: LoggingConfig


class ScanResult(BaseModel):
    """Recordings eligible for archiving, plus why the rest were passed over."""

    recordings: List[Recording] = Field(default_factory=list)
    skipped_archived: int = 0
    skipped_incomplete: int = 0
    skipped_filtered: int = 0
    failed_to_parse: int = 0


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
