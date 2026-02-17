from archiver.models import ArchiverConfig, Recording, ArchiveResult, ArchiveSummary


def test_archiver_config_from_dict():
    config_dict = {
        "superwhisper": {"recordings_path": "/tmp/recordings"},
        "archive": {"repo_path": "/tmp/repo"},
        "filters": {"modes": ["meeting"], "min_duration_ms": 0},
        "logging": {"level": "INFO", "file": "/tmp/test.log"},
    }
    config = ArchiverConfig(**config_dict)
    assert config.superwhisper.recordings_path == "/tmp/recordings"
    assert config.archive.repo_path == "/tmp/repo"
    assert config.filters.modes == ["meeting"]


def test_recording_from_meta_json():
    meta = {
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello world",
        "rawResult": " Hello world",
        "duration": 13647,
        "segments": [{"text": "Hello world", "start": 1.696, "end": 12.864}],
        "modeName": "Meeting",
        "modelName": "Ultra (Cloud)",
        "languageModelName": "GPT-5 mini",
        "languageSelected": "en",
        "systemAudioEnabled": True,
        "appVersion": "2.9.0",
    }
    recording = Recording(source_dir="1770978710", **meta)
    assert recording.source_dir == "1770978710"
    assert recording.modeName == "Meeting"
    assert recording.duration == 13647
    assert len(recording.segments) == 1


def test_recording_with_llm_result():
    meta = {
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello",
        "rawResult": " Hello",
        "duration": 5000,
        "segments": [],
        "modeName": "Meeting",
        "modelName": "Ultra (Cloud)",
        "languageSelected": "en",
        "systemAudioEnabled": True,
        "appVersion": "2.9.0",
        "llmResult": "Summary: greeting exchanged",
    }
    recording = Recording(source_dir="123", **meta)
    assert recording.llmResult == "Summary: greeting exchanged"


def test_recording_without_optional_fields():
    meta = {
        "datetime": "2026-02-13T10:31:50",
        "result": "Hello",
        "rawResult": " Hello",
        "duration": 5000,
        "segments": [],
        "modeName": "Default",
        "modelName": "Ultra (Cloud)",
        "languageSelected": "en",
        "systemAudioEnabled": False,
        "appVersion": "2.9.0",
    }
    recording = Recording(source_dir="123", **meta)
    assert recording.llmResult is None
    assert recording.languageModelName is None


def test_archive_result():
    result = ArchiveResult(
        success=True,
        source_dir="1770978710",
        file_path="2026/02/2026-02-13-10-31-50.md",
        commit_sha="abc123",
    )
    assert result.success
    assert result.error is None


def test_archive_summary():
    summary = ArchiveSummary(
        total_recordings=5,
        archived_count=3,
        failed_count=1,
        skipped_count=1,
        results=[],
    )
    assert summary.total_recordings == 5
