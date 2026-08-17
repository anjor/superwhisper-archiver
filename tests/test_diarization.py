"""Rendering speaker labels from diarized recordings."""

from archiver.markdown_formatter import MarkdownFormatter
from archiver.models import Recording, RecordingGroup, Segment

BASE = {
    "modeName": "Meeting",
    "modelName": "Ultra (Cloud)",
    "languageSelected": "en",
    "systemAudioEnabled": True,
    "appVersion": "2.9.0",
}


def _rec(source_dir="1786959203", datetime="2026-08-17T09:33:23", duration=60000, segments=None):
    segments = [] if segments is None else segments
    text = " ".join(s["text"] for s in segments)
    return Recording(
        source_dir=source_dir,
        datetime=datetime,
        duration=duration,
        result=text,
        rawResult=text,
        segments=segments,
        **BASE,
    )


DIARIZED = [
    {"text": "The problem here has become like, yeah.", "start": 0.0, "end": 6.4, "speaker": 0,
     "confidence": 1},
    {"text": "I'd hire more humans for these.", "start": 7.1, "end": 8.5, "speaker": 0,
     "confidence": 1},
    {"text": "Yeah, that makes sense.", "start": 9.0, "end": 12.0, "speaker": 1, "confidence": 1},
    {"text": "But what about the cost?", "start": 12.5, "end": 15.0, "speaker": 1,
     "confidence": 1},
    {"text": "Good question.", "start": 16.0, "end": 17.0, "speaker": 0, "confidence": 1},
]

PLAIN = [
    {"text": "Hello world.", "start": 1.0, "end": 5.0},
    {"text": "How are you?", "start": 5.5, "end": 12.0},
]


def _format(*recordings):
    return MarkdownFormatter().format_group(RecordingGroup(recordings=list(recordings)))


# --- Parsing ------------------------------------------------------------


def test_segment_parses_speaker_and_confidence():
    seg = Segment(text="hi", start=0.0, end=1.0, speaker=1, confidence=0.9)
    assert seg.speaker == 1
    assert seg.confidence == 0.9


def test_segment_without_diarization_still_parses():
    seg = Segment(text="hi", start=0.0, end=1.0)
    assert seg.speaker is None
    assert seg.confidence is None


def test_speaker_zero_is_preserved_not_treated_as_absent():
    """Speaker ids are 0-based, so falsiness must not be used to detect them."""
    assert Segment(text="hi", start=0.0, end=1.0, speaker=0).speaker == 0


# --- Undiarized output is unchanged --------------------------------------


def test_plain_recording_has_no_speaker_markup():
    md = _format(_rec(segments=PLAIN))
    assert "Speaker" not in md
    assert "## Conversation" not in md
    assert "speaker_count:" not in md


def test_plain_segments_keep_their_format():
    md = _format(_rec(segments=PLAIN))
    assert "- [00:01.0 → 00:05.0] Hello world." in md


# --- Diarized output -----------------------------------------------------


def test_frontmatter_records_the_speaker_count():
    md = _format(_rec(segments=DIARIZED))
    assert "speaker_count: 2" in md


def test_segments_are_labelled_with_their_speaker():
    md = _format(_rec(segments=DIARIZED))
    assert "- [00:00.0 → 00:06.4] **Speaker 0:** The problem here has become like, yeah." in md
    assert "- [00:09.0 → 00:12.0] **Speaker 1:** Yeah, that makes sense." in md


def test_conversation_section_is_added():
    md = _format(_rec(segments=DIARIZED))
    assert "## Conversation" in md


def test_consecutive_segments_from_one_speaker_merge_into_a_turn():
    md = _format(_rec(segments=DIARIZED))
    conversation = md.split("## Conversation", 1)[1].split("## Segments", 1)[0]
    assert "The problem here has become like, yeah. I'd hire more humans for these." in conversation


def test_a_change_of_speaker_starts_a_new_turn():
    md = _format(_rec(segments=DIARIZED))
    conversation = md.split("## Conversation", 1)[1].split("## Segments", 1)[0]
    assert conversation.count("**Speaker 0**") == 2  # speaks, is interrupted, speaks again
    assert conversation.count("**Speaker 1**") == 1


def test_turns_are_stamped_with_their_start_time():
    md = _format(_rec(segments=DIARIZED))
    conversation = md.split("## Conversation", 1)[1]
    assert "**Speaker 1** — 00:09.0" in conversation


# --- Grouped recordings --------------------------------------------------


def test_speaker_numbering_across_parts_is_flagged_not_assumed():
    """Speaker ids are assigned per recording, so part 2's 0 may be someone else."""
    first = _rec("a", "2026-08-17T09:30:00", 20000, DIARIZED)
    second = _rec("b", "2026-08-17T09:30:30", 20000, DIARIZED)
    md = _format(first, second)
    assert "numbering restarts" in md.lower()
    assert "### Part 1" in md.split("## Conversation", 1)[1]


def test_a_group_with_one_diarized_part_needs_no_caveat():
    md = _format(_rec(segments=DIARIZED))
    assert "numbering restarts" not in md.lower()


def test_group_speaker_count_does_not_sum_across_parts():
    """Two parts with two speakers each is not four speakers."""
    first = _rec("a", "2026-08-17T09:30:00", 20000, DIARIZED)
    second = _rec("b", "2026-08-17T09:30:30", 20000, DIARIZED)
    md = _format(first, second)
    assert "speaker_count: 2" in md


def test_mixed_group_only_renders_conversation_for_diarized_parts():
    diarized = _rec("a", "2026-08-17T09:30:00", 20000, DIARIZED)
    plain = _rec("b", "2026-08-17T09:30:30", 20000, PLAIN)
    md = _format(diarized, plain)
    assert "## Conversation" in md
    conversation = md.split("## Conversation", 1)[1].split("## Segments", 1)[0]
    assert "Hello world." not in conversation
