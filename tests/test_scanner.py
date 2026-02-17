import json
from pathlib import Path

from archiver.scanner import Scanner
from archiver.models import Recording


def _create_recording(tmp_path: Path, dir_name: str, meta: dict):
    """Helper to create a fake recording directory."""
    rec_dir = tmp_path / dir_name
    rec_dir.mkdir()
    (rec_dir / "meta.json").write_text(json.dumps(meta))


MEETING_META = {
    "datetime": "2026-02-13T10:31:50",
    "result": "Hello world",
    "rawResult": " Hello world",
    "duration": 13647,
    "segments": [{"text": "Hello world", "start": 1.0, "end": 12.0}],
    "modeName": "Meeting",
    "modelName": "Ultra (Cloud)",
    "languageSelected": "en",
    "systemAudioEnabled": True,
    "appVersion": "2.9.0",
}

DEFAULT_META = {
    **MEETING_META,
    "modeName": "Default",
    "datetime": "2026-02-14T09:00:00",
}


def test_scan_finds_recordings(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", DEFAULT_META)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan()
    assert len(recordings) == 2


def test_scan_filters_by_mode(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", DEFAULT_META)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan(modes=["meeting"])
    assert len(recordings) == 1
    assert recordings[0].modeName == "Meeting"


def test_scan_filters_by_min_duration(tmp_path):
    short_meta = {**MEETING_META, "duration": 100}
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", short_meta)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan(min_duration_ms=1000)
    assert len(recordings) == 1


def test_scan_filters_by_since_date(tmp_path):
    old_meta = {**MEETING_META, "datetime": "2026-02-01T10:00:00"}
    _create_recording(tmp_path, "1770978710", MEETING_META)
    _create_recording(tmp_path, "1770978720", old_meta)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan(since="2026-02-10")
    assert len(recordings) == 1


def test_scan_skips_invalid_directories(tmp_path):
    _create_recording(tmp_path, "1770978710", MEETING_META)
    # Create a directory without meta.json
    (tmp_path / "invalid_dir").mkdir()
    # Create a non-directory file
    (tmp_path / "random_file.txt").write_text("hello")
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan()
    assert len(recordings) == 1


def test_scan_returns_sorted_by_datetime(tmp_path):
    early = {**MEETING_META, "datetime": "2026-02-10T08:00:00"}
    late = {**MEETING_META, "datetime": "2026-02-15T18:00:00"}
    _create_recording(tmp_path, "1770978720", late)
    _create_recording(tmp_path, "1770978710", early)
    scanner = Scanner(str(tmp_path))
    recordings = scanner.scan()
    assert recordings[0].datetime == "2026-02-10T08:00:00"
    assert recordings[1].datetime == "2026-02-15T18:00:00"
