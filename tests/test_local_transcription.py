"""Transcribing on this Mac what superwhisper finished without a transcript."""

import json
import os
import shutil
import tempfile
import time
import wave
from pathlib import Path

import pytest
from git import Repo

from archiver import main
from archiver.git_manager import GitManager
from archiver.main import archive_group, run_archiver, select_pending, with_cached_transcripts
from archiver.markdown_formatter import MarkdownFormatter
from archiver.models import ArchiverConfig, LocalTranscript, Recording, RecordingGroup, Segment
from archiver.state_tracker import StateTracker

LOCAL_TEXT = "Shall we start with the roadmap?"
LOCAL_SEGMENTS = [Segment(text=LOCAL_TEXT, start=0.5, end=3.0)]

# What superwhisper 3.0 writes when it cannot reach its cloud API.
OFFLINE_META = {
    "datetime": "2026-11-24T09:00:00",
    "kind": "meeting",
    "modeName": "Meeting",
    "modelName": "S1-Voice (Cloud)",
    "languageSelected": "en",
    "appVersion": "3.0.1",
    "duration": 0,
    "result": "",
    "rawResult": "",
    "segments": [],
    "llmResult": "Not enough was said in this meeting to summarize.",
}

FILTERS = ArchiverConfig.FiltersConfig(modes=["meeting"], min_duration_ms=60000)


def _offline(source_dir="1795000000", **overrides) -> Recording:
    """An offline meeting as the scanner hands it over, length read from its audio."""
    meta = {**OFFLINE_META, "duration": 1800000, "audio_file": "output.ogg", **overrides}
    return Recording(source_dir=source_dir, **meta)


class FakeTranscribe:
    def __init__(self, segments=LOCAL_SEGMENTS):
        self.segments = segments
        self.calls = []

    def __call__(self, recording: Recording) -> LocalTranscript:
        self.calls.append(recording.source_dir)
        return LocalTranscript(model="distil-large-v3", segments=self.segments)


def _init_repo(path: Path) -> Repo:
    repo = Repo.init(path, initial_branch="main")
    repo.config_writer().set_value("user", "name", "Test").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()
    (path / "README.md").write_text("seed")
    repo.index.add(["README.md"])
    repo.index.commit("seed")
    return repo


@pytest.fixture
def notes():
    path = Path(tempfile.mkdtemp())
    _init_repo(path)
    yield path
    shutil.rmtree(path)


@pytest.fixture
def tracker(tmp_path):
    return StateTracker(str(tmp_path / "state.db"))


def _archive(group, notes, tracker, transcribe, dry_run=False):
    return archive_group(
        group, MarkdownFormatter(), GitManager(str(notes)), tracker, transcribe, dry_run
    )


# --- Selection ----------------------------------------------------------


def test_archived_note_without_a_transcript_is_rewritten_until_transcribed(tracker):
    """An existing stub note is picked up again, and left alone once transcribed."""
    group = RecordingGroup(recordings=[_offline()])
    archived = {"1795000000"}
    assert select_pending([group], FILTERS, archived) == [group]

    tracker.save_local_transcript(
        "1795000000", LocalTranscript(model="distil-large-v3", segments=LOCAL_SEGMENTS)
    )
    transcribed = RecordingGroup(recordings=with_cached_transcripts(group.recordings, tracker))

    assert select_pending([transcribed], FILTERS, archived) == []


def test_archived_note_without_audio_is_left_alone():
    """With nothing to transcribe, the stub note is the final word."""
    group = RecordingGroup(recordings=[_offline(audio_file=None)])
    assert select_pending([group], FILTERS, {"1795000000"}) == []


def test_unarchived_group_is_pending_and_archived_group_is_not():
    done = RecordingGroup(recordings=[_offline(result="Hello.", rawResult="Hello.")])
    assert select_pending([done], FILTERS, set()) == [done]
    assert select_pending([done], FILTERS, {"1795000000"}) == []


def test_cached_transcript_never_replaces_one_from_superwhisper(tracker):
    tracker.save_local_transcript(
        "1795000000", LocalTranscript(model="distil-large-v3", segments=LOCAL_SEGMENTS)
    )
    rec = _offline(result="superwhisper's text", rawResult="superwhisper's text")
    assert with_cached_transcripts([rec], tracker) == [rec]


# --- Archiving ----------------------------------------------------------


def test_archive_writes_the_local_transcript_into_the_note(notes, tracker):
    transcribe = FakeTranscribe()

    result = _archive(RecordingGroup(recordings=[_offline()]), notes, tracker, transcribe)

    assert result.success
    assert transcribe.calls == ["1795000000"]
    note = (notes / result.file_path).read_text()
    assert LOCAL_TEXT in note
    assert 'local_transcription_model: "distil-large-v3"' in note
    assert "transcription_failed" not in note
    assert tracker.get_local_transcripts(["1795000000"]) == {
        "1795000000": LocalTranscript(model="distil-large-v3", segments=LOCAL_SEGMENTS)
    }
    assert tracker.is_archived("1795000000")


def test_failed_commit_saves_no_transcript(notes, tracker):
    """Otherwise the recording would count as transcribed and never get its note."""
    fresh_lock = notes / ".git" / "index.lock"
    fresh_lock.write_text("")
    transcribe = FakeTranscribe()

    result = _archive(RecordingGroup(recordings=[_offline()]), notes, tracker, transcribe)

    assert not result.success
    assert transcribe.calls == ["1795000000"]
    assert tracker.get_local_transcripts(["1795000000"]) == {}
    assert not tracker.is_archived("1795000000")


def test_transcription_error_fails_the_group(notes, tracker):
    def broken(recording):
        raise RuntimeError("model would not load")

    result = _archive(RecordingGroup(recordings=[_offline()]), notes, tracker, broken)

    assert not result.success
    assert "model would not load" in result.error
    assert not tracker.is_archived("1795000000")


def test_dry_run_never_transcribes(notes, tracker, capsys):
    transcribe = FakeTranscribe()

    result = _archive(
        RecordingGroup(recordings=[_offline()]), notes, tracker, transcribe, dry_run=True
    )

    assert result.success
    assert transcribe.calls == []
    assert "transcribing 1 locally" in capsys.readouterr().out
    assert not (notes / result.file_path).exists()
    assert tracker.get_local_transcripts(["1795000000"]) == {}


def test_silent_recording_keeps_its_failure_notice_and_is_not_retried(notes, tracker):
    transcribe = FakeTranscribe(segments=[])
    group = RecordingGroup(recordings=[_offline()])

    result = _archive(group, notes, tracker, transcribe)

    note = (notes / result.file_path).read_text()
    assert "transcription_failed: true" in note
    assert "## Transcription Failed" in note
    next_run = RecordingGroup(recordings=with_cached_transcripts(group.recordings, tracker))
    assert select_pending([next_run], FILTERS, tracker.get_archived_source_dirs()) == []


# --- Whole runs ---------------------------------------------------------


def _write_silence(path: Path, seconds: int = 70, rate: int = 8000):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(b"\0\0" * rate * seconds)


def _recording_dir(recordings: Path, source_dir: str, meta: dict) -> Path:
    rec_dir = recordings / source_dir
    rec_dir.mkdir(parents=True)
    (rec_dir / "meta.json").write_text(json.dumps(meta))
    _write_silence(rec_dir / "output.wav")
    hours_ago = time.time() - 3 * 3600
    os.utime(rec_dir / "meta.json", (hours_ago, hours_ago))
    return rec_dir


def test_two_runs_transcribe_each_recording_once(tmp_path, monkeypatch):
    """Today's offline meeting is archived, and an old stub note is rewritten in place."""
    recordings = tmp_path / "recordings"
    offline = _recording_dir(recordings, "1795000000", OFFLINE_META)
    stub = _recording_dir(
        recordings,
        "1790000000",
        {**OFFLINE_META, "datetime": "2026-09-27T10:00:00", "duration": 70000,
         "llmResult": None, "languageSelected": ""},
    )

    origin = tmp_path / "origin.git"
    Repo.init(origin, bare=True, initial_branch="main")
    notes_repo = _init_repo(tmp_path / "notes")
    notes_repo.create_remote("origin", str(origin)).push("main")
    stub_note = "2026/09/2026-09-27-10-00-00.md"
    (tmp_path / "notes" / "2026" / "09").mkdir(parents=True)
    (tmp_path / "notes" / stub_note).write_text("transcription_failed: true\n")
    notes_repo.index.add([stub_note])
    notes_repo.index.commit("Archive: stub")

    state_db = tmp_path / "state.db"
    StateTracker(str(state_db)).mark_archived(
        "1790000000", "2026-09-27T10:00:00", "Meeting", 70000, stub_note, "sha"
    )

    calls = []

    class FakeTranscriber:
        def __init__(self, model):
            self.model = model

        def __call__(self, audio_path, language):
            calls.append((audio_path, language))
            return LocalTranscript(model=self.model, segments=LOCAL_SEGMENTS)

    monkeypatch.setattr(main, "LocalTranscriber", FakeTranscriber)
    monkeypatch.setattr(main, "default_state_db_path", lambda: state_db)
    config = ArchiverConfig(
        superwhisper={"recordings_path": str(recordings)},
        archive={"repo_path": str(tmp_path / "notes")},
        filters={"modes": ["meeting"], "min_duration_ms": 60000},
        logging={},
    )

    first = run_archiver(config)
    second = run_archiver(config)

    assert first.archived_count == 2
    assert sorted(calls) == [(stub / "output.wav", None), (offline / "output.wav", "en")]
    for path in (stub_note, "2026/11/2026-11-24-09-00-00.md"):
        note = (tmp_path / "notes" / path).read_text()
        assert LOCAL_TEXT in note
        assert "transcription_failed" not in note
    assert second.total_recordings == 0
    assert len(calls) == 2
