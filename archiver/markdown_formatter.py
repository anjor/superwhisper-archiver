"""Formats superwhisper recordings as Markdown."""

from datetime import datetime
import logging

from .models import Recording, RecordingGroup

logger = logging.getLogger(__name__)


class MarkdownFormatter:
    """Formats superwhisper recordings as Markdown with YAML frontmatter."""

    def format_group(self, group: RecordingGroup) -> str:
        """Format a group of recordings as a single Markdown note.

        A group of one renders exactly as a lone recording always did, so
        notes written before grouping existed stay comparable.
        """
        return self._build_frontmatter(group) + self._build_body(group)

    def _build_frontmatter(self, group: RecordingGroup) -> str:
        rec = group.primary
        parts = [
            "---",
            f'datetime: "{group.datetime}"',
            f"mode: {group.modeName}",
            f"duration_ms: {group.duration}",
            f'model: "{rec.modelName}"',
        ]
        if rec.languageModelName:
            parts.append(f'language_model: "{rec.languageModelName}"')
        parts.extend([
            f"language: {rec.languageSelected}",
            f"system_audio: {str(rec.systemAudioEnabled).lower()}",
            f'app_version: "{rec.appVersion}"',
        ])

        if group.speaker_count:
            parts.append(f"speaker_count: {group.speaker_count}")

        if len(group.recordings) == 1:
            parts.append(f'source_dir: "{rec.source_dir}"')
        else:
            parts.append(f"recording_count: {len(group.recordings)}")
            parts.append("source_dirs:")
            parts.extend(f'  - "{source_dir}"' for source_dir in group.source_dirs)

        parts.extend([
            f'archived_at: "{datetime.now().isoformat()}"',
            "---",
        ])
        return "\n".join(parts) + "\n"

    def _build_body(self, group: RecordingGroup) -> str:
        start = datetime.fromisoformat(group.datetime)
        duration_str = self._format_duration(group.duration)

        parts = [
            f"\n# Recording — {start.strftime('%Y-%m-%d %H:%M')}\n",
            f"**Mode**: {group.modeName} | **Duration**: {duration_str}\n",
        ]
        if len(group.recordings) > 1:
            parts.append(
                f"*Assembled from {len(group.recordings)} consecutive recordings.*\n"
            )

        transcription = self._build_transcription(group)
        if transcription:
            parts.append(f"## Transcription\n\n{transcription}\n")

        summary = "\n\n".join(r.llmResult.strip() for r in group.recordings if r.llmResult)
        if summary:
            parts.append(f"## Summary\n\n{summary}\n")

        conversation = self._build_conversation(group)
        if conversation:
            parts.append(f"## Conversation\n\n{conversation}\n")

        segments = self._build_segments(group)
        if segments:
            parts.append(f"## Segments\n\n{segments}\n")

        parts.append(f"\n---\n*Archived: {datetime.now().strftime('%Y-%m-%d')}*\n")

        return "\n".join(parts)

    def _build_transcription(self, group: RecordingGroup) -> str:
        """Concatenate each part's transcript, in order.

        Parts are labelled when there is more than one, so a reader can tell a
        gap in the conversation from a pause in it.
        """
        blocks = []
        for index, rec in enumerate(group.recordings, start=1):
            text = (rec.result or rec.rawResult or "").strip()
            if not text:
                continue
            if len(group.recordings) > 1:
                offset = self._format_timestamp(self._offset_seconds(group, rec))
                blocks.append(f"### Part {index} — {offset}\n\n{text}")
            else:
                blocks.append(text)
        return "\n\n".join(blocks)

    def _build_conversation(self, group: RecordingGroup) -> str:
        """A speaker-attributed reading of the transcript.

        Only produced for diarized recordings. Consecutive segments from the
        same speaker are joined into one turn, which reads far better than a
        line per segment.
        """
        diarized = group.diarized_recordings
        if not diarized:
            return ""

        blocks = []
        if len(diarized) > 1:
            blocks.append(
                "*Speaker numbering restarts with each part — "
                "Speaker 0 in one part is not necessarily Speaker 0 in another.*"
            )

        for rec in diarized:
            if len(diarized) > 1:
                index = group.recordings.index(rec) + 1
                blocks.append(f"### Part {index}")
            offset = self._offset_seconds(group, rec)
            blocks.extend(self._build_turns(rec, offset))

        return "\n\n".join(blocks)

    def _build_turns(self, recording: Recording, offset: float) -> list:
        """Merge each speaker's consecutive segments into a single turn."""
        turns = []
        current_speaker = None
        texts = []
        started_at = 0.0

        def flush():
            if texts:
                stamp = self._format_timestamp(started_at + offset)
                turns.append(f"**Speaker {current_speaker}** — {stamp}\n\n{' '.join(texts)}")

        for seg in recording.segments:
            if seg.speaker is None:
                continue
            if seg.speaker != current_speaker:
                flush()
                current_speaker = seg.speaker
                texts = []
                started_at = seg.start
            texts.append(seg.text.strip())
        flush()

        return turns

    def _build_segments(self, group: RecordingGroup) -> str:
        """Segment timings, shifted so they run continuously across parts.

        Each recording times its segments from its own start, so every part
        after the first is offset by its distance from the group's start.
        """
        lines = []
        for rec in group.recordings:
            offset = self._offset_seconds(group, rec)
            for seg in rec.segments:
                start = self._format_timestamp(seg.start + offset)
                end = self._format_timestamp(seg.end + offset)
                speaker = f"**Speaker {seg.speaker}:** " if seg.speaker is not None else ""
                lines.append(f"- [{start} → {end}] {speaker}{seg.text}")
        return "\n".join(lines)

    @staticmethod
    def _offset_seconds(group: RecordingGroup, recording: Recording) -> float:
        """How far into the group this recording starts, in seconds."""
        group_start = datetime.fromisoformat(group.datetime)
        return (datetime.fromisoformat(recording.datetime) - group_start).total_seconds()

    def compute_file_path(self, group: RecordingGroup) -> str:
        """Compute the archive file path for a group.

        Derived from the earliest recording, so that a later recording joining
        the group rewrites the same note rather than creating a second one.

        Returns:
            Relative path like YYYY/MM/YYYY-MM-DD-HH-MM-SS.md
        """
        dt = datetime.fromisoformat(group.datetime)
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        filename = dt.strftime("%Y-%m-%d-%H-%M-%S") + ".md"
        return f"{year}/{month}/{filename}"

    @staticmethod
    def _format_duration(duration_ms: int) -> str:
        total_seconds = duration_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as MM:SS.s"""
        mins = int(seconds) // 60
        secs = seconds - (mins * 60)
        return f"{mins:02d}:{secs:04.1f}"
