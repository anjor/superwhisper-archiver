"""Pydantic models for the superwhisper archiver."""

from typing import Optional, List
from pydantic import BaseModel, Field


class Segment(BaseModel):
    text: str
    start: float
    end: float


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

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        file: str = "/tmp/superwhisper-archiver.log"

    superwhisper: SuperwhisperConfig
    archive: ArchiveConfig
    filters: FiltersConfig
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
