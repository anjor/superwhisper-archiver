"""Pydantic models for the superwhisper archiver."""

from typing import Optional, List
from pydantic import BaseModel, Field


class Segment(BaseModel):
    text: str
    start: float
    end: float


class Recording(BaseModel):
    """A parsed superwhisper recording from meta.json."""

    source_dir: str
    datetime: str
    result: str
    rawResult: str
    duration: int  # milliseconds
    segments: List[Segment]
    modeName: str
    modelName: str
    languageSelected: str
    systemAudioEnabled: bool
    appVersion: str
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
        modes: List[str] = Field(default_factory=lambda: ["meeting"])
        min_duration_ms: int = 0

    class LoggingConfig(BaseModel):
        level: str = "INFO"
        file: str = "/tmp/superwhisper-archiver.log"

    superwhisper: SuperwhisperConfig
    archive: ArchiveConfig
    filters: FiltersConfig
    logging: LoggingConfig


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
